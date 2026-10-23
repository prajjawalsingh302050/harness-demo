# CLAUDE.md

Guidance for AI coding assistants (Claude Code and others) working in this repository.

## What this repo is

A **demo** of harness engineering: a tiny app with one `people` table and **deliberately planted problems**, sensors that detect them,
and a Gemini coding agent that fixes them through PRs. See [README.md](README.md) and [ARCHITECTURE.md](ARCHITECTURE.md).

## The most important rule

**The planted problems are intentional. Do not fix them unless the user explicitly asks.**
They are the input to the demo. Fixing them by hand on `main` breaks the demo.

Planted on purpose (each one is caught by one of the four sensors):
- dead code: `import json` and `format_phone()` in `app/routes.py`, `public/js/legacy-charts.js`
- unused libraries: `requests` and `python-dateutil` in `requirements.txt`
- p95 latency: `list_people` in `app/routes.py` looks up each person by email (no index) — 5,001 queries for "Load 5000 people"
- error rate: the HTTP 500 for a missing person in `app/routes.py`

## Sensors

Only four, on purpose: **dead code** and **unused libraries** (continuous drift detection),
**p95 latency `/api/people?limit=5000`** and **error rate** (continuous runtime feedback).
Don't add more sensors unless the user asks.

If the user wants them fixed, do it on a branch and open a PR, the same way the agent does.
To restore them afterwards: `bash scripts/demo_reset.sh`.

## Commands

```bash
uv venv .venv --python 3.12
uv pip install -p .venv -r requirements.txt -r requirements-dev.txt

.venv/bin/uvicorn api.index:app --reload          # UI + API on :8000
.venv/bin/python -m pytest -q                      # tests
.venv/bin/python scripts/build_db.py               # rebuild data/shop.db after changing migrations
.venv/bin/python scripts/build_db.py --check       # CI check: DB matches migrations
PYTHON=.venv/bin/python bash scripts/run_sensors.sh   # all sensors → reports/health-report.md
.venv/bin/python scripts/agent.py                  # Gemini agent (needs GEMINI_API_KEY in .env)
```

## Conventions

- **Python 3.12**, FastAPI, standard-library `sqlite3`. Sync route functions (SQLite is blocking).
- **Flat backend on purpose:** `api/index.py` (app + middleware), `app/routes.py` (endpoints), `app/db.py` (database). Keep it simple.
- **All SQL goes through `app.db.query()`**, so it is counted in `X-DB-Queries` and slow queries are logged.
- **Never edit `migrations/001_init.sql`.** Add a new numbered file (`002_*.sql`, `003_*.sql`), then run `scripts/build_db.py` and commit `data/shop.db`.
- **Keep API response shapes stable.** The UI in `public/js/` depends on them.
- **Frontend is plain HTML/CSS/JS.** No framework, no build step. Every page loads `/js/api.js` or `/js/config.js` plus its own script.
  A JS file that no HTML page loads is reported as dead code.
- **Don't add rewrites to `vercel.json`.** Vercel's FastAPI preset routes `/api/*` to `api/index.py`; a rewrite breaks every route.
- Keep `.vercelignore` excluding tests, scripts, reports and dev requirements.

## Harness files: change with care

These define what "healthy" means and how the agent behaves. Changing them changes the demo:

| File | Role |
|---|---|
| `budgets.json` | Pass/fail thresholds |
| `scripts/build_report.py` | Check logic (dead code, unused libraries, latency, error rate) and report format |
| `scripts/collect_runtime.py` | Load test: 2 workers on "Load 5000", 3 on person lookups (every 5th ID missing) + health |
| `scripts/run_sensors.sh` | Sensor order, vulture flags |
| `scripts/agent.py` | Agent rules, allowed paths (`EDITABLE`, `PROTECTED`), verification |
| `.github/workflows/health-check.yml` | The loop in CI |

After changing any of them, run the sensors on the planted code (expect 4 of 4 failing) **and** on a fixed copy
(expect 4 of 4 passing) before committing.

## Secrets and accounts

- `GEMINI_API_KEY` lives in `.env` (git-ignored) locally and as a GitHub secret. Never print or commit it.
- GitHub: `prajjawalsingh302050/harness-demo`. Vercel project `harness-demo`, production <https://harness-demo-beige.vercel.app>.
- Repo variable `APP_URL` points the runtime sensors at production.

## Git

- `main` is what Vercel deploys. Work on branches and open PRs.
- The `demo-start` tag marks the planted state used by `demo_reset.sh`. Move it only when the planted state itself changes on purpose.
