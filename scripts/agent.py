"""Coding agent: read the health report, ask Gemini for fixes, apply them, verify, write the PR text.

    python scripts/agent.py          # needs GEMINI_API_KEY (from the environment or .env)

Exit code 0 = changes applied and tests pass, 1 = nothing safe to propose.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
# Base URL of the Gemini REST API.
API = "https://generativelanguage.googleapis.com/v1beta"

# Files sent to Gemini as context (each under 60 KB).
CONTEXT_GLOBS = ["requirements.txt", "migrations/*.sql", "app/**/*.py", "api/*.py",
                 "tests/*.py", "public/*.html", "public/js/*.js"]
# The only places the agent may write. Anything else is rejected by safe_path().
EDITABLE = ("app/", "api/", "tests/", "migrations/", "public/", "requirements.txt")
# Never edited, even though it is under an editable folder.
PROTECTED = {"migrations/001_init.sql"}
# First try plus one retry with the test failure as feedback.
MAX_ATTEMPTS = 1
# HTTP statuses worth retrying: rate limit and temporary server trouble (e.g. 503 "high demand").
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}
# Waits between retries of one model, in seconds; then the next model is tried.
BACKOFF_SECONDS = (10, 20, 30)
# Never wait longer than this for one retry, even if the server asks for more.
MAX_WAIT_SECONDS = 60
# How many models to try in total before giving up.
MAX_MODELS = 2

# System instruction sent with every request.
RULES = """You are the coding agent inside a software harness. Sensors produced a health report.
Make every failing check pass with the smallest correct changes.

Rules:
- Only change files under app/, api/, tests/, migrations/, public/, and requirements.txt.
- For action "write", return the COMPLETE new file content, not a diff.
- Never edit migrations/001_init.sql. Add indexes in a NEW file such as migrations/002_add_indexes.sql
  using CREATE INDEX IF NOT EXISTS.
- Keep the backend flat: app/routes.py holds the endpoints, app/db.py the database access.
  All SQL must go through app.db.query() so it is counted.
- Keep every API path and JSON response shape the same so the UI keeps working:
  /api/people?limit=N returns {count, people: [{id, name, email, city}]} ordered by id (max 5000),
  /api/people/{id} returns {id, name, email, city}, /api/health returns {status: "ok"}.
- Do not hide problems: no skipping or deleting tests, no catch-all exception handlers, no raising budgets,
  no deleting logging just to silence a warning. Fix the cause.
- Dead code: delete only what is unused everywhere in the repo. Keep sqlite3 row_factory.
  If your own fix leaves a function unused (e.g. an old lookup helper), delete it too.
- Unused libraries: remove packages from requirements.txt that no file in app/ or api/ imports. Keep fastapi.
- Tests: when you change behaviour, add a test that asserts the status code and concrete values
  (e.g. a missing person returns 404). Keep the existing tests passing.
  The database has one table, people, with ids 1..10000.
- pr_title: short, imperative.
- pr_body: Markdown. One section per failing check: what the sensor found -> what you changed -> why it fixes it.
"""

# The exact JSON shape Gemini must answer in.
SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "pr_title": {"type": "STRING"},
        "pr_body": {"type": "STRING"},
        "changes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "action": {"type": "STRING", "enum": ["write", "delete"]},
                    "content": {"type": "STRING"},
                    "reason": {"type": "STRING"},
                },
                "required": ["path", "action", "reason"],
            },
        },
    },
    "required": ["pr_title", "pr_body", "changes"],
}


def load_env():
    """Load KEY=value lines from .env without overriding variables that are already set."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class GeminiUnavailable(Exception):
    """A model stayed unavailable (overloaded, rate-limited or unreachable) after all retries."""


def request(url, key, payload=None):
    """Call the Gemini API (POST with a payload, GET without) and return the JSON reply.

    Temporary failures (429/5xx, network errors, timeouts) are retried with backoff. If they
    persist, GeminiUnavailable is raised so the caller can try another model. Any other error
    (bad key, unknown model, bad request) stops the agent with the server's message.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    last_error = ""
    for attempt in range(len(BACKOFF_SECONDS) + 1):
        if attempt:
            wait = BACKOFF_SECONDS[attempt - 1]
            print(f"    retry {attempt}/{len(BACKOFF_SECONDS)} in {wait}s ({last_error})")
            time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:500]
            if exc.code not in TRANSIENT_STATUSES:
                raise SystemExit(f"Gemini API error {exc.code}: {body}")
            last_error = f"HTTP {exc.code}"
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if retry_after and retry_after.isdigit() and attempt < len(BACKOFF_SECONDS):
                # Honour the server's hint for the next wait, within limits.
                hinted = min(int(retry_after), MAX_WAIT_SECONDS)
                if hinted > BACKOFF_SECONDS[attempt]:
                    print(f"    server asked to wait {hinted}s")
                    time.sleep(hinted - BACKOFF_SECONDS[attempt])
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = f"network: {getattr(exc, 'reason', exc)}"
    raise GeminiUnavailable(last_error)


def _version(name):
    match = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return float(match.group(1)) if match else 0.0


def candidate_models(key):
    """Return the models to try, in order.

    GEMINI_MODEL="a,b" uses exactly that order. GEMINI_MODEL="a" tries a first, then fallbacks.
    Fallbacks are this key's stable "flash" models (newest first), then stable "pro" models.
    """
    pinned = [m.strip() for m in os.environ.get("GEMINI_MODEL", "").split(",") if m.strip()]
    if len(pinned) > 1:
        return pinned
    try:
        models = request(f"{API}/models?pageSize=200", key).get("models", [])
    except GeminiUnavailable as exc:
        if pinned:
            return pinned
        raise SystemExit(f"Could not list Gemini models ({exc}). Set GEMINI_MODEL and try again.")
    names = [m["name"].split("/", 1)[1] for m in models
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    skip = ("lite", "image", "tts", "live", "audio", "embedding", "exp", "preview", "thinking")
    stable = [n for n in names if n.startswith("gemini-") and not any(s in n for s in skip)]
    flash = sorted((n for n in stable if "flash" in n), key=_version, reverse=True)
    pro = sorted((n for n in stable if "pro" in n), key=_version, reverse=True)
    ordered = []
    for name in pinned + flash + pro:
        if name not in ordered:
            ordered.append(name)
    if not ordered:
        raise SystemExit("No usable Gemini model with generateContent is available for this key. Set GEMINI_MODEL.")
    return ordered[:MAX_MODELS]


def repo_files():
    """Read every file matching CONTEXT_GLOBS into {relative path: text}."""
    files = {}
    for pattern in CONTEXT_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file() and path.stat().st_size < 60_000:
                files[str(path.relative_to(ROOT))] = path.read_text()
    return files


def build_prompt(report_md, files, feedback):
    """Join the health report, every source file and, on a retry, the previous failure into one message."""
    parts = ["# Health report\n", report_md, "\n# Repository files\n"]
    for path, content in files.items():
        parts.append(f"\n--- FILE: {path} ---\n{content}")
    if feedback:
        parts.append("\n# Your previous attempt failed verification. Fix this and return the full set of changes again:\n")
        parts.append(feedback)
    return "".join(parts)


def call_gemini(key, models, prompt):
    """Ask Gemini for a fix, trying each model in turn; return (answer dict, model that answered)."""
    payload = {
        "systemInstruction": {"parts": [{"text": RULES}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA, "temperature": 0.2},
    }
    for model in models:
        print(f"  asking {model}...")
        try:
            data = request(f"{API}/models/{model}:generateContent", key, payload)
        except GeminiUnavailable as exc:
            print(f"  {model} is unavailable ({exc}); trying the next model")
            continue
        try:
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
            return json.loads(text), model
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            print(f"  {model} gave an unreadable answer ({exc}); trying the next model")
    raise SystemExit(f"All models were unavailable: {', '.join(models)}. Re-run the workflow later.")


def safe_path(raw):
    """Return the path if the agent may write it, else None (blocks .., absolute, protected and other paths)."""
    path = raw.strip().lstrip("./")
    if not path or ".." in Path(path).parts or path.startswith("/"):
        return None
    if path in PROTECTED or not (path.startswith(EDITABLE) or path == "requirements.txt"):
        return None
    return path


def apply_changes(changes, backup):
    """Write or delete each allowed file, saving originals in `backup`; return (applied, rejected)."""
    applied, rejected = [], []
    for change in changes:
        path = safe_path(change.get("path", ""))
        if not path:
            rejected.append(change.get("path", "?"))
            continue
        target = ROOT / path
        backup.setdefault(path, target.read_text() if target.exists() else None)
        if change["action"] == "delete":
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(change.get("content", ""))
        applied.append((change["action"], path, change.get("reason", "")))
    return applied, rejected


def restore(backup):
    """Put every backed-up file back, deleting files that did not exist before."""
    for path, content in backup.items():
        target = ROOT / path
        if content is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)


def verify():
    """Rebuild the database and run the tests; return (passed, error output)."""
    steps = [[sys.executable, "scripts/build_db.py"], [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]]
    for cmd in steps:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        last = (result.stdout + result.stderr).strip().splitlines()[-1:] or [""]
        print(f"  verify: {' '.join(cmd[1:])} -> {'ok' if result.returncode == 0 else 'FAILED'} ({last[0]})")
        if result.returncode != 0:
            return False, f"$ {' '.join(cmd[1:])}\n{(result.stdout + result.stderr)[-3000:]}"
    return True, ""


def main():
    """Read the report, ask Gemini, apply, verify, and on success write the PR text. Returns the exit code."""
    load_env()
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set (add it to .env or the GitHub secret).")

    report_json = REPORTS / "health-report.json"
    if not report_json.exists():
        raise SystemExit("No reports/health-report.json. Run: bash scripts/run_sensors.sh")
    report = json.loads(report_json.read_text())
    if report["healthy"]:
        print("All checks pass. No action needed.")
        return 0

    print("Failing checks:")
    for c in report["checks"]:
        if not c["ok"]:
            print(f"  - {c['name']}: {c['value']} (budget {c['budget']})")
    models = candidate_models(key)
    print(f"Agent models, in order: {', '.join(models)}")
    report_md = (REPORTS / "health-report.md").read_text()
    files = repo_files()
    print(f"Context: health-report.md ({len(report_md)} chars) + {len(files)} source files "
          f"({sum(len(t) for t in files.values())} chars): {', '.join(files)}")
    feedback, backup = "", {}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"Attempt {attempt}: asking Gemini for fixes to {report['failed']} failing check(s)...")
        started = time.monotonic()
        answer, model = call_gemini(key, models, build_prompt(report_md, files, feedback))
        print(f"  {model} answered in {time.monotonic() - started:.1f}s with {len(answer.get('changes', []))} change(s): "
              f"\"{answer.get('pr_title', '').strip()}\"")
        restore(backup)
        backup = {}
        applied, rejected = apply_changes(answer.get("changes", []), backup)
        for action, path, reason in applied:
            print(f"  {action:6} {path}  - {reason}")
        if rejected:
            print(f"  rejected (outside allowed paths): {', '.join(rejected)}")
        ok, feedback = verify()
        if ok:
            write_pr(answer, applied, model, report_md)
            print("Verification passed (DB rebuilt, tests green). PR text written to reports/.")
            return 0
        print(f"  verification failed:\n{feedback[-1200:]}")

    restore(backup)
    subprocess.run([sys.executable, "scripts/build_db.py"], cwd=ROOT, capture_output=True)
    print("Giving up: no change set passed verification. Repository restored.")
    return 1


def write_pr(answer, applied, model, report_md):
    """Write reports/pr-title.txt and reports/pr-body.md for the workflow to open the pull request."""
    changed = "\n".join(f"- `{path}` ({action}): {reason}" for action, path, reason in applied)
    body = (
        f"{answer['pr_body'].strip()}\n\n"
        f"## Files changed\n{changed}\n\n"
        "## Verification\n- Database rebuilt from migrations\n- Test suite passes\n"
        "- Re-run the **health-check** workflow after merging to confirm every sensor is green.\n\n"
        f"<details><summary>Health report that triggered this PR</summary>\n\n{report_md}\n</details>\n\n"
        f"_Opened by the harness coding agent ({model}). A human must review and merge._\n"
    )
    (REPORTS / "pr-title.txt").write_text(answer["pr_title"].strip().splitlines()[0][:120])
    (REPORTS / "pr-body.md").write_text(body)


if __name__ == "__main__":
    sys.exit(main())
