"""Combine the sensor outputs into reports/health-report.json and reports/health-report.md.

Three checks: dead code (continuous drift detection), p95 latency and error rate (continuous runtime feedback).
Each check has:
  kind  computational (deterministic tool) or inferential (needs judgement; the agent confirms)
  area  codebase (continuous drift detection) or runtime (continuous runtime feedback)
"""
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


# ---------- runtime sensors ----------

def runtime_source():
    live, local = load_json("runtime-live.json"), load_json("runtime-local.json")
    return (live, "live (Vercel)") if live else (local, "local (CI)")


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
    stats = runtime["by_endpoint"]["orders"]
    budget = BUDGETS["orders_p95_ms"]
    details = [
        f"p50 {stats['p50_ms']} ms, p95 {stats['p95_ms']} ms, DB time p95 {stats['db_p95_ms']} ms over {stats['requests']} requests",
        f"Each page of 50 orders runs {stats['avg_db_queries']} DB queries on average (X-DB-Queries header)",
    ]
    return check(
        "latency_orders", f"p95 latency /api/orders [{source}]", "computational", "runtime",
        f"{stats['p95_ms']:.0f} ms", f"{budget} ms", stats["p95_ms"] <= budget,
        details + slow_query_details(), ["app/services/orders.py", "app/repositories/orders.py", "migrations/"],
        "Find where the time goes. If one request runs a query per order (N+1), add a repository method that fetches "
        "the page with one query that JOINs users and aggregates order_items, and use it from the service. Keep the "
        "response shape identical. If a slow "
        "query does a full table scan, add a NEW migration (e.g. migrations/002_add_indexes.sql) with CREATE INDEX. "
        "Never edit 001_init.sql.",
    )


def error_rate(runtime, source):
    rate = runtime["error_rate_pct"]
    users = runtime["by_endpoint"]["users"]
    return check(
        "error_rate", f"Error rate (HTTP 5xx) [{source}]", "computational", "runtime",
        f"{rate}%", f"{BUDGETS['error_rate_pct']}%", rate <= BUDGETS["error_rate_pct"],
        [f"/api/users/{{id}} returned {users['errors_5xx']} server errors out of {users['requests']} requests (lookups of customer IDs that do not exist)"] if users["errors_5xx"] else [],
        ["app/services/users.py", "app/api/routes/users.py"],
        "Return HTTP 404 with a clear message when the customer does not exist instead of crashing.",
    )


def main():
    runtime, source = runtime_source()
    checks = [dead_code()]
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
