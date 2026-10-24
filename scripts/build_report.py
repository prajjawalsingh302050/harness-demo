"""Combine the sensor outputs into reports/health-report.json and reports/health-report.md.

Four checks: dead code and unused libraries (continuous drift detection),
p95 latency and error rate (continuous runtime feedback).
Each check has:
  kind  computational (deterministic tool) or inferential (needs judgement; the agent confirms)
  area  codebase (continuous drift detection) or runtime (continuous runtime feedback)
"""
import ast
import json
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
# The pass/fail limits. Changing them changes what "healthy" means.
BUDGETS = json.loads((ROOT / "budgets.json").read_text())


def load_json(path):
    """Read reports/<path> as JSON, or return None if it is missing or empty."""
    path = REPORTS / path
    return json.loads(path.read_text()) if path.exists() and path.stat().st_size else None


def check(id_, name, kind, area, value, budget, ok, details=None, files=None, hint=""):
    """Build one check record: value vs budget, plus evidence (details), where to look (files) and a hint."""
    return {
        "id": id_, "name": name, "kind": kind, "area": area,
        "value": value, "budget": budget, "ok": bool(ok),
        "details": details or [], "files": files or [], "hint": hint,
    }


# ---------- codebase sensors ----------

def dead_code():
    """Check 1: unused Python code (from vulture) plus JS files that no HTML page loads."""
    details, files = [], set()
    vulture = REPORTS / "vulture.txt"
    if vulture.exists():
        for line in vulture.read_text().splitlines():
            if ":" in line and "unused" in line:
                details.append(line.strip())
                files.add(line.split(":")[0])

    # JavaScript files in public/js that no HTML page loads.
    html = " ".join(p.read_text() for p in (ROOT / "public").glob("*.html"))
    for js in sorted((ROOT / "public" / "js").glob("*.js")):
        if f"/js/{js.name}" not in html:
            details.append(f"public/js/{js.name}: file is never loaded by any HTML page")
            files.add(f"public/js/{js.name}")

    return check(
        "dead_code", "Dead code (vulture + unreferenced JS)", "inferential", "codebase",
        len(details), BUDGETS["dead_code_items"], len(details) <= BUDGETS["dead_code_items"],
        details, sorted(files),
        "Confirm each item is truly unused (search the repo), then delete it. Delete whole files that become empty.",
    )


# Package names whose import name differs from the name in requirements.txt.
IMPORT_NAMES = {"python-dateutil": "dateutil", "pyyaml": "yaml", "beautifulsoup4": "bs4", "pillow": "PIL",
                "scikit-learn": "sklearn", "python-dotenv": "dotenv"}


def unused_dependencies():
    """Packages in requirements.txt that no file in app/ or api/ imports."""
    imported = set()
    for path in [*(ROOT / "app").rglob("*.py"), *(ROOT / "api").rglob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])

    details = []
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        package = re.split(r"[<>=!~\[;\s]", line.strip(), maxsplit=1)[0]
        if not package or package.startswith("#"):
            continue
        module = IMPORT_NAMES.get(package.lower(), package.lower().replace("-", "_"))
        if module not in imported:
            details.append(f"{line.strip()}: listed in requirements.txt but never imported in app/ or api/")
    return check(
        "unused_dependencies", "Unused libraries in requirements.txt", "computational", "codebase",
        len(details), BUDGETS["unused_dependencies"], len(details) <= BUDGETS["unused_dependencies"],
        details, ["requirements.txt"],
        "Remove each library the code never imports. Vercel installs everything in requirements.txt.",
    )


# ---------- runtime sensors ----------

def runtime_source():
    """Use the live site's load-test numbers if they exist, else the local ones."""
    live, local = load_json("runtime-live.json"), load_json("runtime-local.json")
    return (live, "live (Vercel)") if live else (local, "local (CI)")


def _is_full_table_scan(plan_line, sql, tables):
    """A plan line like 'SCAN order_items' on a real table, with no index. Aliases are resolved."""
    match = re.match(r"SCAN (\w+)", plan_line)
    if not match or "INDEX" in plan_line or not re.search(r"\bWHERE\b", sql, re.IGNORECASE):
        return False
    aliases = {}
    for table, alias in re.findall(r"\b(?:FROM|JOIN)\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?", sql, re.IGNORECASE):
        aliases[table] = table
        if alias and alias.upper() not in {"WHERE", "JOIN", "ON", "ORDER", "GROUP", "LIMIT", "LEFT", "INNER", "CROSS"}:
            aliases[alias] = table
    return aliases.get(match.group(1), match.group(1)) in tables


def slow_query_details():
    """Explain the most frequent slow queries from the local app log, flagging full table scans."""
    log = REPORTS / "app.log"
    counts = Counter()
    if log.exists():
        for line in log.read_text(errors="ignore").splitlines():
            match = re.search(r"slow query [\d.]+ms: (.+)$", line)
            if match:
                counts[match.group(1).strip()] += 1

    details = []
    con = sqlite3.connect(f"file:{ROOT / 'data' / 'shop.db'}?mode=ro", uri=True)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for sql, n in counts.most_common(3):
        try:
            plan = [row[3] for row in con.execute("EXPLAIN QUERY PLAN " + sql, [1] * sql.count("?"))]
        except sqlite3.Error as exc:
            plan = [f"(could not explain: {exc})"]
        scan = " FULL TABLE SCAN" if any(_is_full_table_scan(p, sql, tables) for p in plan) else ""
        details.append(f"{n}x slow query{scan}: {sql}  ->  plan: {' | '.join(plan)}")
    con.close()
    return details


def latency(runtime, source):
    """Check 3: p95 latency of "Load 5000 people", with query counts and slow-query plans as evidence."""
    stats = runtime["by_endpoint"]["people"]
    budget = BUDGETS["people_p95_ms"]
    details = [
        f"p50 {stats['p50_ms']} ms, p95 {stats['p95_ms']} ms, DB time p95 {stats['db_p95_ms']} ms over {stats['requests']} requests",
        f"Loading 5000 people runs {stats['avg_db_queries']} DB queries on average (X-DB-Queries header)",
    ]
    return check(
        "latency_people", f"p95 latency /api/people?limit=5000 [{source}]", "computational", "runtime",
        f"{stats['p95_ms']:.0f} ms", f"{budget} ms", stats["p95_ms"] <= budget,
        details + slow_query_details(), ["app/routes.py"],
        "Find where the time goes. If the endpoint runs one query per person (N+1), fetch the whole list with one "
        "SELECT ... ORDER BY id LIMIT ? and keep the response shape {count, people: [{id, name, email, city}]}. "
        "Delete helpers that become unused. If you need an index, add a NEW migration (e.g. migrations/002_*.sql); "
        "never edit 001_init.sql.",
    )


def error_rate(runtime, source):
    """Check 4: share of requests that ended in a server error (5xx)."""
    rate = runtime["error_rate_pct"]
    person = runtime["by_endpoint"]["person"]
    return check(
        "error_rate", f"Error rate (HTTP 5xx) [{source}]", "computational", "runtime",
        f"{rate}%", f"{BUDGETS['error_rate_pct']}%", rate <= BUDGETS["error_rate_pct"],
        [f"/api/people/{{id}} returned {person['errors_5xx']} server errors out of {person['requests']} requests (lookups of person IDs that do not exist)"] if person["errors_5xx"] else [],
        ["app/routes.py"],
        "Return HTTP 404 with a clear message when the person does not exist instead of crashing.",
    )


def main():
    """Run every check, write health-report.json and .md, and tell GitHub Actions whether it is healthy."""
    runtime, source = runtime_source()
    checks = [dead_code(), unused_dependencies()]
    if runtime:
        checks += [latency(runtime, source), error_rate(runtime, source)]

    failed = [c for c in checks if not c["ok"]]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": os.environ.get("GITHUB_SHA", "local")[:7],
        "healthy": not failed,
        "failed": len(failed),
        "checks": checks,
    }
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "health-report.json").write_text(json.dumps(report, indent=2))
    (REPORTS / "health-report.md").write_text(to_markdown(report))

    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as out:
            out.write(f"healthy={'true' if report['healthy'] else 'false'}\n")
    for c in checks:
        print(f"  {'PASS' if c['ok'] else 'FAIL'}  {c['name']}: {c['value']} (budget {c['budget']})")
    if not runtime:
        print("  (no load-test results found, so latency and error rate were not checked)")
    print(f"healthy={report['healthy']} failed={len(failed)}/{len(checks)}")
    print("Wrote reports/health-report.json and reports/health-report.md")


def to_markdown(report):
    """Render the report as Markdown: a table of all checks, then a section per failing check."""
    icon = {"computational": "🟦", "inferential": "🟥"}
    status = "🟢 all checks pass" if report["healthy"] else f"🔴 {report['failed']} failing"
    lines = [
        f"# Health report: {status}",
        "",
        f"Generated {report['generated_at']} for commit `{report['commit']}`. "
        "🟦 computational (deterministic tool) · 🟥 inferential (needs judgement).",
        "",
        "| Check | Kind | Area | Value | Budget | Result |",
        "|---|---|---|---|---|---|",
    ]
    for c in report["checks"]:
        lines.append(f"| {c['name']} | {icon[c['kind']]} | {c['area']} | {c['value']} | {c['budget']} | {'✅' if c['ok'] else '❌'} |")
    failing = [c for c in report["checks"] if not c["ok"]]
    if failing:
        lines += ["", "## Failing checks", ""]
        for c in failing:
            lines += [f"### ❌ {c['name']}", ""]
            lines += [f"- {d}" for d in c["details"]] or ["- (no details)"]
            if c["files"]:
                lines.append(f"- Files: {', '.join('`' + f + '`' for f in c['files'])}")
            if c["hint"]:
                lines.append(f"- Suggested direction: {c['hint']}")
            lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
