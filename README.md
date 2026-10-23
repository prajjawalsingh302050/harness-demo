# Harness Demo: continuous drift and health sensors

A live demo of the "continuous drift and health sensors" idea from Martin Fowler's
[Harness Engineering](https://martinfowler.com/articles/harness-engineering.html) article.

A small shop app (HTML/CSS/JS + FastAPI on Vercel) ships with **planted problems**.
A GitHub Action runs **sensors** against the codebase and the running app, builds a
**health report**, and a **Gemini coding agent** fixes the failures and opens a **pull request**.
A human merges, Vercel redeploys, the sensors run again, and the report turns green.

```
 sensors (GitHub Actions)  ──►  health report  ──►  Gemini agent  ──►  PR  ──►  human merges  ──►  Vercel deploys
          ▲                                                                                            │
          └──────────────────────────────────── run again ◄───────────────────────────────────────────┘
```

## Sensors

| Diagram box | Check | Tool | Kind |
|---|---|---|---|
| dependabot | Vulnerable dependencies | `pip-audit` | 🟦 computational |
| /find-dead-code | Dead code | `vulture` + unreferenced JS scan, confirmed by the agent | 🟥 inferential |
| /code-coverage-quality | Tests that would not catch a bug | AST check + coverage, confirmed by the agent | 🟥 inferential |
| latency | p95 latency of `/api/orders`, `/api/users/{id}` | load test (`collect_runtime.py`) | 🟦 computational |
| latency (cause) | DB queries per request (N+1) | `X-DB-Queries` response header | 🟦 computational |
| error rate | HTTP 5xx rate | load test | 🟦 computational |
| availability | `/api/health` success rate | load test | 🟦 computational |
| slow queries | Slow queries doing full table scans | slow-query log + `EXPLAIN QUERY PLAN` | 🟦 computational |
| /log-anomalies | The same warning repeated on most requests | log aggregation, root cause by the agent | 🟥 inferential |

"Healthy" is defined by [`budgets.json`](budgets.json), not by the AI.

## Planted problems

| Problem | Where |
|---|---|
| Old `requests`, `urllib3`, `idna`, `certifi` with known CVEs | `requirements.txt` |
| Unused module, unused function, unused import, unloaded JS file | `app/services/legacy_discount.py`, `pricing.py`, `orders.py`, `public/js/legacy-charts.js` |
| Tests that only check `is not None` / truthiness | `tests/test_api.py` |
| N+1 queries: 101 queries per orders page | `app/routes/orders.py` |
| Missing index on `order_items.order_id` | `migrations/001_init.sql` |
| Crash (HTTP 500) when a customer does not exist | `app/routes/users.py` |
| Warning logged for most orders (missing tax mapping) | `app/services/pricing.py` |

## Setup

1. **Gemini key** (free): <https://aistudio.google.com/apikey>
   - Local: `cp .env.example .env` and set `GEMINI_API_KEY`.
   - GitHub: `gh secret set GEMINI_API_KEY` (paste the key when asked).
2. Local environment:
   ```bash
   uv venv .venv && uv pip install -p .venv -r requirements.txt -r requirements-dev.txt
   .venv/bin/uvicorn api.index:app --reload        # http://127.0.0.1:8000
   ```

## Run the loop

**In GitHub (the demo):** Actions → **health-check** → **Run workflow**.

**Locally:**
```bash
PYTHON=.venv/bin/python bash scripts/run_sensors.sh   # sensors + reports/health-report.md
.venv/bin/python scripts/agent.py                     # Gemini fixes the code in your working tree
PYTHON=.venv/bin/python bash scripts/run_sensors.sh   # should now be all green
```

## Demo script (about 5 minutes)

1. Open the app. The Orders page shows **~1 s and 101 DB queries**; customer `5000` gives **HTTP 500**.
2. Run **health-check**. The job summary and `/health.html` show the report: **8 checks failing**.
3. The agent opens a PR. Each change maps to a failing check, with the evidence in the description.
4. Vercel posts a preview URL on the PR. Open it: the Orders page is now fast.
5. Merge the PR (the human-approval step). Vercel deploys to production.
6. Run **health-check** again. **All checks pass**; no PR is opened. `/health.html` shows red → green.
7. Reset for the next audience: `bash scripts/demo_reset.sh` (opens a PR that re-plants everything).

## Guardrails

- The agent can only edit `app/`, `api/`, `tests/`, `migrations/`, `public/` and `requirements.txt`.
  It cannot touch workflows, scripts, budgets or `001_init.sql`.
- Every change set is verified (database rebuilt, tests pass) before a PR is opened; a failing attempt is rolled back and retried once.
- The agent only opens pull requests. A human reviews and merges.

## Project layout

```
public/            UI (HTML, CSS, JS) incl. health.html
api/index.py       FastAPI entry point (Vercel Python function)
app/               routes, DB access, services
migrations/        SQL schema; data/shop.db is built from these
scripts/           sensors, report, agent, publish, reset
budgets.json       what "healthy" means
.github/workflows  health-check (sensors → agent → PR) and ci (tests)
```
