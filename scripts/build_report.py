"""Combine all sensor outputs into reports/health-report.json and reports/health-report.md.

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
BUDGETS = json.loads((ROOT / "budgets.json").read_text())


def load_json(path):
    path = REPORTS / path
    return json.loads(path.read_text()) if path.exists() and path.stat().st_size else None


def check(id_, name, kind, area, value, budget, ok, details=None, files=None, hint=""):
    return {
        "id": id_, "name": name, "kind": kind, "area": area,
        "value": value, "budget": budget, "ok": bool(ok),
        "details": details or [], "files": files or [], "hint": hint,
    }


# ---------- codebase sensors ----------

def vulnerable_dependencies():
    data = load_json("pip-audit.json") or {}
    details = []
    for dep in data.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            fixes = ", ".join(vuln.get("fix_versions") or []) or "no fix listed"
            details.append(f"{dep['name']} {dep['version']}: {vuln['id']} (fixed in {fixes})")
    return check(
        "dependencies", "Vulnerable dependencies (pip-audit)", "computational", "codebase",
        len(details), BUDGETS["vulnerabilities"], len(details) <= BUDGETS["vulnerabilities"],
        details, ["requirements.txt"],
        "Upgrade each package to a fixed version, or remove packages the code never imports.",
    )


def dead_code():
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


def _weak_assert(node):
    """True when an assert only checks existence or truthiness (assert x, assert x is not None)."""
    test = node.test
    if isinstance(test, (ast.Name, ast.Attribute, ast.Call, ast.Subscript)):
        return True
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], (ast.IsNot, ast.Is)):
        comparator = test.comparators[0]
        return isinstance(comparator, ast.Constant) and comparator.value is None
    return False


def weak_tests():
    details, files = [], set()
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text())
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]:
            asserts = [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]
            if not asserts or all(_weak_assert(a) for a in asserts):
                rel = path.relative_to(ROOT)
                details.append(f"{rel}::{fn.name} only checks that something exists or is truthy; it would pass even if the API returned wrong data or an error")
                files.add(str(rel))
    coverage = load_json("coverage.json")
    if coverage:
        details.append(f"Line coverage of app/: {coverage['totals']['percent_covered_display']}% (coverage alone does not prove the tests catch bugs)")
    weak = len([d for d in details if "::" in d])
    return check(
        "weak_tests", "Test quality (asserts that catch real bugs)", "inferential", "codebase",
        weak, BUDGETS["weak_tests"], weak <= BUDGETS["weak_tests"],
        details, sorted(files),
        "Rewrite tests to assert status codes and real values (e.g. 200 with the expected fields, 404 for a missing customer).",
    )


# ---------- runtime sensors ----------

def runtime_source():
    live, local = load_json("runtime-live.json"), load_json("runtime-local.json")
    return (live, "live (Vercel)") if live else (local, "local (CI)")


def latency_checks(runtime, source):
    checks = []
    for endpoint, key, budget_key, files in (
        ("orders", "/api/orders", "orders_p95_ms", ["app/routes/orders.py"]),
        ("users", "/api/users/{id}", "users_p95_ms", ["app/routes/users.py"]),
    ):
        stats = runtime["by_endpoint"][endpoint]
        budget = BUDGETS[budget_key]
        checks.append(check(
            f"latency_{endpoint}", f"p95 latency {key} [{source}]", "computational", "runtime",
            f"{stats['p95_ms']:.0f} ms", f"{budget} ms", stats["p95_ms"] <= budget,
            [f"p50 {stats['p50_ms']} ms, p95 {stats['p95_ms']} ms, DB time p95 {stats['db_p95_ms']} ms over {stats['requests']} requests"],
            files,
            "Look at the DB query count and slow-query checks for the cause.",
        ))
    return checks


def query_count(runtime, source):
    avg = runtime["by_endpoint"]["orders"]["avg_db_queries"]
    budget = BUDGETS["db_queries_per_request"]
    return check(
        "db_queries", f"DB queries per /api/orders request [{source}]", "computational", "runtime",
        avg, budget, avg <= budget,
        [f"Each page of 50 orders runs {avg} queries on average: one per order for the customer and one per order for the total (N+1 pattern)"] if avg > budget else [],
        ["app/routes/orders.py"],
        "Fetch the page with one query that JOINs users and aggregates order_items with GROUP BY. Keep the JSON response shape identical.",
    )


def error_rate(runtime, source):
    rate = runtime["error_rate_pct"]
    users = runtime["by_endpoint"]["users"]
    return check(
        "error_rate", f"Error rate (HTTP 5xx) [{source}]", "computational", "runtime",
        f"{rate}%", f"{BUDGETS['error_rate_pct']}%", rate <= BUDGETS["error_rate_pct"],
        [f"/api/users/{{id}} returned {users['errors_5xx']} server errors out of {users['requests']} requests (lookups of customer IDs that do not exist)"] if users["errors_5xx"] else [],
        ["app/routes/users.py"],
        "Return HTTP 404 with a clear message when the customer does not exist instead of crashing.",
    )


def availability(runtime, source):
    value = runtime["availability_pct"]
    return check(
        "availability", f"Availability /api/health [{source}]", "computational", "runtime",
        f"{value}%", f"{BUDGETS['availability_pct']}%", value >= BUDGETS["availability_pct"],
    )


def _is_full_table_scan(plan_line, sql, tables):
    """A plan line like 'SCAN order_items' on a real table, with no index. Aliases are resolved."""
    match = re.match(r"SCAN (\w+)", plan_line)
    if not match or "INDEX" in plan_line:
        return False
    aliases = {}
    for table, alias in re.findall(r"\b(?:FROM|JOIN)\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?", sql, re.IGNORECASE):
        aliases[table] = table
        if alias and alias.upper() not in {"WHERE", "JOIN", "ON", "ORDER", "GROUP", "LIMIT", "LEFT", "INNER", "CROSS"}:
            aliases[alias] = table
    return aliases.get(match.group(1), match.group(1)) in tables


def slow_queries():
    log = REPORTS / "app.log"
    counts = Counter()
    if log.exists():
        for line in log.read_text(errors="ignore").splitlines():
            match = re.search(r"slow query [\d.]+ms: (.+)$", line)
            if match:
                counts[match.group(1).strip()] += 1

    details, full_scans = [], 0
    con = sqlite3.connect(f"file:{ROOT / 'data' / 'shop.db'}?mode=ro", uri=True)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for sql, n in counts.most_common(5):
        try:
            plan = [row[3] for row in con.execute("EXPLAIN QUERY PLAN " + sql, [1] * sql.count("?"))]
        except sqlite3.Error as exc:
            plan = [f"(could not explain: {exc})"]
        scans = [p for p in plan if _is_full_table_scan(p, sql, tables)]
        full_scans += 1 if scans else 0
        details.append(f"{n}x slow: {sql}  ->  plan: {' | '.join(plan)}")
    con.close()
    return check(
        "slow_queries", "Slow queries doing full table scans (EXPLAIN QUERY PLAN)", "computational", "runtime",
        full_scans, BUDGETS["slow_queries_with_full_scan"], full_scans <= BUDGETS["slow_queries_with_full_scan"],
        details, ["migrations/"],
        "Add a NEW migration file (e.g. migrations/002_add_indexes.sql) with CREATE INDEX for the scanned column. Never edit 001_init.sql.",
    )


def log_anomalies():
    log = REPORTS / "app.log"
    counts = Counter()
    if log.exists():
        for line in log.read_text(errors="ignore").splitlines():
            if line.startswith("WARNING") and "slow query" not in line:
                counts[re.sub(r"=\S+", "=<value>", re.sub(r"\d+(\.\d+)?", "<n>", line))] += 1
    top = counts.most_common(3)
    worst = top[0][1] if top else 0
    budget = BUDGETS["repeated_log_warnings"]
    return check(
        "log_anomalies", "Repeated log warnings", "inferential", "runtime",
        worst, f"< {budget}", worst < budget,
        [f"{n}x {msg}" for msg, n in top],
        ["app/services/pricing.py"],
        "Find why the same warning fires on almost every request and fix the cause (for example a missing mapping), rather than just hiding the log.",
    )


def main():
    runtime, source = runtime_source()
    checks = [vulnerable_dependencies(), dead_code(), weak_tests()]
    if runtime:
        checks += latency_checks(runtime, source)
        checks += [query_count(runtime, source), error_rate(runtime, source), availability(runtime, source)]
    checks += [slow_queries(), log_anomalies()]

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
    print(f"healthy={report['healthy']} failed={len(failed)}/{len(checks)}")


def to_markdown(report):
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
