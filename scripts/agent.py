"""Coding agent: read the health report, ask Gemini for fixes, apply them, verify, write the PR text.

    python scripts/agent.py          # needs GEMINI_API_KEY (from the environment or .env)

Exit code 0 = changes applied and tests pass, 1 = nothing safe to propose.
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
API = "https://generativelanguage.googleapis.com/v1beta"

CONTEXT_GLOBS = ["requirements.txt", "migrations/*.sql", "app/**/*.py", "api/*.py",
                 "tests/*.py", "public/*.html", "public/js/*.js"]
EDITABLE = ("app/", "api/", "tests/", "migrations/", "public/", "requirements.txt")
PROTECTED = {"migrations/001_init.sql"}
MAX_ATTEMPTS = 2

RULES = """You are the coding agent inside a software harness. Sensors produced a health report.
Make every failing check pass with the smallest correct changes.

Rules:
- Only change files under app/, api/, tests/, migrations/, public/, and requirements.txt.
- For action "write", return the COMPLETE new file content, not a diff.
- Never edit migrations/001_init.sql. Add indexes in a NEW file such as migrations/002_add_indexes.sql
  using CREATE INDEX IF NOT EXISTS.
- Respect the layers: app/api/routes/ only handles HTTP and calls the service registry; app/services/ holds
  business logic; app/repositories/ holds every SQL statement, run through app.db.query();
  app/services/registry.py wires repositories into services. Response models are in app/schemas/.
- Keep every API path and JSON response shape the same so the UI keeps working.
  /api/orders must still return {page, page_size, orders: [{id, customer, city, created_at, status, total}]}
  with the same totals (price_with_tax applied to the order's item sum).
- Do not hide problems: no skipping or deleting tests, no catch-all exception handlers, no raising budgets,
  no deleting logging just to silence a warning. Fix the cause.
- Dead code: delete only what is unused everywhere in the repo. Keep sqlite3 row_factory.
  If your own fix leaves a function or method unused (e.g. an old repository method), delete it too.
- Tests: when you change behaviour, add a test that asserts the status code and concrete values
  (e.g. a missing customer returns 404). Keep the existing tests passing.
  The database has users with ids 1..2000, 20000 orders, and the orders page size is 50.
- pr_title: short, imperative.
- pr_body: Markdown. One section per failing check: what the sensor found -> what you changed -> why it fixes it.
"""

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
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def request(url, key, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Gemini API error {exc.code}: {exc.read().decode()[:500]}")


def pick_model(key):
    if os.environ.get("GEMINI_MODEL"):
        return os.environ["GEMINI_MODEL"]
    models = request(f"{API}/models?pageSize=200", key).get("models", [])
    names = [m["name"].split("/", 1)[1] for m in models
             if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in m["name"]]
    skip = ("lite", "image", "tts", "live", "audio", "embedding", "exp", "preview", "thinking")

    def version(name):
        match = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
        return float(match.group(1)) if match else 0.0

    stable = sorted((n for n in names if not any(s in n for s in skip)), key=version, reverse=True)
    if stable:
        return stable[0]
    if names:
        return sorted(names, key=version, reverse=True)[0]
    raise SystemExit("No Gemini 'flash' model with generateContent is available for this key. Set GEMINI_MODEL.")


def repo_files():
    files = {}
    for pattern in CONTEXT_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file() and path.stat().st_size < 60_000:
                files[str(path.relative_to(ROOT))] = path.read_text()
    return files


def build_prompt(report_md, files, feedback):
    parts = ["# Health report\n", report_md, "\n# Repository files\n"]
    for path, content in files.items():
        parts.append(f"\n--- FILE: {path} ---\n{content}")
    if feedback:
        parts.append("\n# Your previous attempt failed verification. Fix this and return the full set of changes again:\n")
        parts.append(feedback)
    return "".join(parts)


def call_gemini(key, model, prompt):
    payload = {
        "systemInstruction": {"parts": [{"text": RULES}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA, "temperature": 0.2},
    }
    data = request(f"{API}/models/{model}:generateContent", key, payload)
    try:
        text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        return json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not parse Gemini response: {exc}\n{json.dumps(data)[:800]}")


def safe_path(raw):
    path = raw.strip().lstrip("./")
    if not path or ".." in Path(path).parts or path.startswith("/"):
        return None
    if path in PROTECTED or not (path.startswith(EDITABLE) or path == "requirements.txt"):
        return None
    return path


def apply_changes(changes, backup):
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
    for path, content in backup.items():
        target = ROOT / path
        if content is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)


def verify():
    steps = [[sys.executable, "scripts/build_db.py"], [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]]
    for cmd in steps:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            return False, f"$ {' '.join(cmd[1:])}\n{(result.stdout + result.stderr)[-3000:]}"
    return True, ""


def main():
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

    model = pick_model(key)
    print(f"Agent model: {model}")
    report_md = (REPORTS / "health-report.md").read_text()
    files = repo_files()
    feedback, backup = "", {}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"Attempt {attempt}: asking Gemini for fixes to {report['failed']} failing check(s)...")
        answer = call_gemini(key, model, build_prompt(report_md, files, feedback))
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
