# Harness Demo: continuous drift and health sensors

A small, working demo of the **"continuous drift and health sensors"** idea from Martin Fowler's article
[Harness Engineering](https://martinfowler.com/articles/harness-engineering.html).

A tiny app with **one table of 10,000 people** ships with **planted problems**.
A GitHub Action runs **four sensors** against the code and the live deployment, builds a **health report**,
and a **Gemini coding agent** fixes what fails and opens a **pull request**.
A human merges, Vercel redeploys, the sensors run again, and the report turns green.

| | |
|---|---|
| Live app | <https://harness-demo-beige.vercel.app> |
| How it works (in the app) | <https://harness-demo-beige.vercel.app/architecture.html> |
| Health report | <https://harness-demo-beige.vercel.app/health.html> |
| Architecture details | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Notes for AI coding assistants | [CLAUDE.md](CLAUDE.md) |

```
   ┌──────────────── GitHub Actions: health-check ────────────────┐
   │  drift detection (codebase)   runtime feedback (live app)    │
   │  • dead code                  • p95 latency "Load 5000"      │
   │  • unused libraries           • error rate                   │
   └───────────────┬──────────────────────────────────────────────┘
                   ▼
        health report (budgets.json)  ──►  /health.html
                   │ failing?
                   ▼
        Gemini coding agent  ──►  rebuild DB + run tests  ──►  pull request
                                                                   │ human merges
                                                                   ▼
                                                   Vercel deploys ──► run health-check again
```

---

## What the demo shows

| Diagram half | Sensor here | Kind |
|---|---|---|
| **Continuous drift detection** (codebase) | **Dead code**: `vulture` + JS files no page loads | 🟥 inferential |
| | **Unused libraries**: packages in `requirements.txt` that no code imports | 🟦 computational |
| **Continuous runtime feedback** (runtime) | **p95 latency** of the "Load 5000 people" request | 🟦 computational |
| | **Error rate** (HTTP 5xx) | 🟦 computational |

- 🟦 **Computational**: a deterministic tool. Same input, same answer.
- 🟥 **Inferential**: needs judgement. The tool produces evidence and the agent decides what it means.

**"Healthy" is defined by numbers in [`budgets.json`](budgets.json), not by the AI.**

## The app

### Database

One SQLite table, built by [`scripts/build_db.py`](scripts/build_db.py) from [`migrations/001_init.sql`](migrations/001_init.sql):

```sql
CREATE TABLE people (
    id      INTEGER PRIMARY KEY,   -- 1 .. 10000
    name    TEXT NOT NULL,         -- "Ishaan Sharma"
    email   TEXT NOT NULL,         -- "ishaan.sharma1@example.com"   (no index)
    city    TEXT NOT NULL          -- one of 16 Indian cities
);
```

The data is generated from a fixed seed, so every build is identical. The file `data/shop.db` (about 0.5 MB) is committed and opened read-only.

### Backend (flat and minimal)

| File | What it does |
|---|---|
| [`api/index.py`](api/index.py) | Creates the FastAPI app, adds the timing middleware (`X-DB-Queries`, `Server-Timing` headers), includes the routes, serves `public/` locally. Vercel's entry point. |
| [`app/routes.py`](app/routes.py) | The three endpoints |
| [`app/db.py`](app/db.py) | `connect()` opens SQLite read-only; `query()` runs SQL, counts it per request and logs `slow query` over 5 ms |

| Endpoint | Returns |
|---|---|
| `GET /api/people?limit=N` | `{count, people: [{id, name, email, city}]}`, first N people by id (default 50, max 5000) |
| `GET /api/people/{id}` | `{id, name, email, city}` |
| `GET /api/health` | `{status: "ok"}` |
| `GET /api/docs` | Swagger UI |

### Frontend

Plain HTML, CSS and JavaScript in `public/`. No framework, no build step.

| Page | Purpose |
|---|---|
| `index.html` + `js/app.js` | People table with **Load 50 people** and **Load 5000 people** buttons. Pills show response time, DB queries and HTTP status. |
| `person.html` + `js/person.js` | Look up one person by ID (`15000` shows the planted HTTP 500) |
| `health.html` + `js/health.js` | Latest health report and red/green history, read from the `health-reports` branch |
| `architecture.html` + `js/architecture.js` | How it works, with live API buttons |
| `js/api.js`, `js/config.js` | Fetch helper that reads the timing headers; repo settings |
| `js/legacy-charts.js` | **Planted dead code.** No page loads it. |

## Planted problems

| # | Problem | Where | Sensor that finds it | Expected fix |
|---|---|---|---|---|
| 1 | Unused `import json` and unused function `format_phone()` | `app/routes.py` | dead code | Delete |
| 2 | `legacy-charts.js` is never loaded | `public/js/` | dead code | Delete |
| 3 | `requests` and `python-dateutil` are listed but never imported | `requirements.txt` | unused libraries | Remove |
| 4 | "Load 5000 people" fetches the emails, then looks up **each person by email** (no index): 5,001 queries, each scanning the table | `app/routes.py` | p95 latency | One `SELECT … ORDER BY id LIMIT ?` |
| 5 | `None["id"]` crash for a missing person → HTTP 500 | `app/routes.py` | error rate | Return HTTP 404 |

Measured locally:

| | Planted | Fixed |
|---|---|---|
| "Load 5000 people" (single request) | ~1.6 s, 5,001 queries | ~50 ms, 1 query |
| "Load 5000 people" p95 under load | ~4.6 s | ~0.5 s |
| Error rate | ~11% | 0% |
| Checks passing | 0 / 4 | 4 / 4 |

## Sensors and budgets

All sensors run through [`scripts/run_sensors.sh`](scripts/run_sensors.sh), in GitHub Actions and locally.

| # | Check | How | Budget |
|---|---|---|---|
| 1 | Dead code | `vulture app api` + scan for `public/js/*.js` not referenced by any HTML page | 0 items |
| 2 | Unused libraries | parse `requirements.txt`, compare with every `import` in `app/` and `api/` | 0 |
| 3 | p95 latency `/api/people?limit=5000` | load test ([`scripts/collect_runtime.py`](scripts/collect_runtime.py)) | 1000 ms |
| 4 | Error rate (HTTP 5xx) | load test: 2 workers keep clicking "Load 5000", 3 workers do person lookups (every 5th uses an ID that doesn't exist) and health checks | ≤ 1% |

Runtime checks measure the **live Vercel deployment** when `APP_URL` is set, and the local server otherwise.
The latency check attaches evidence for the agent: queries per request, and `EXPLAIN QUERY PLAN` for slow queries that scan the table.

Outputs (in `reports/`, git-ignored): `health-report.json`, `health-report.md` (also the agent's input),
`vulture.txt`, `runtime-local.json`, `runtime-live.json`, `app.log`.

## The coding agent

[`scripts/agent.py`](scripts/agent.py) calls the Gemini REST API directly (no SDK).

1. Reads `reports/health-report.md` and the source files.
2. Picks a model: `GEMINI_MODEL` if set, otherwise the newest stable Gemini "flash" model.
3. Asks for JSON: `pr_title`, `pr_body`, and full-file `write` / `delete` changes.
4. Applies only changes inside `app/`, `api/`, `tests/`, `migrations/`, `public/` and `requirements.txt`.
   Workflows, scripts, budgets and `001_init.sql` are off-limits.
5. **Verifies**: rebuilds `data/shop.db` and runs the tests. On failure it rolls back, sends the error to Gemini and retries once.
6. Writes `reports/pr-title.txt` and `reports/pr-body.md`. The workflow opens the PR. A human merges.

## Setup

### 1. Gemini API key (free)

1. Create a key at <https://aistudio.google.com/apikey>.
2. Local: `cp .env.example .env` and set `GEMINI_API_KEY=…` (`.env` is git-ignored).
3. GitHub: `gh secret set GEMINI_API_KEY --repo prajjawalsingh302050/harness-demo`.

### 2. GitHub settings (already done)

- **Settings → Actions → General → Workflow permissions:** "Read and write" and "Allow GitHub Actions to create and approve pull requests".
- **Variables:** `APP_URL` = the production URL. Optional `GEMINI_MODEL`.

### 3. Vercel (already done)

The project is linked to this repo: pushes to `main` deploy to production, PRs get preview URLs.
`vercel.json` needs no routes. `.vercelignore` keeps tests, scripts and reports out of the deployment.

## Running locally

```bash
uv venv .venv --python 3.12
uv pip install -p .venv -r requirements.txt -r requirements-dev.txt

.venv/bin/uvicorn api.index:app --reload                 # UI + API on http://127.0.0.1:8000
PYTHON=.venv/bin/python bash scripts/run_sensors.sh      # sensors → reports/health-report.md
.venv/bin/python scripts/agent.py                        # agent (edits your working tree)
.venv/bin/python -m pytest -q                            # tests
.venv/bin/python scripts/build_db.py                     # rebuild data/shop.db after changing migrations
```

Undo a local agent run: `git restore . && git clean -fd app tests migrations public`.

## Running the loop in GitHub

| Workflow | Trigger | Steps |
|---|---|---|
| `health-check` | Manual (**Actions → health-check → Run workflow**) and daily at 08:00 IST | Install → sensors (local + live) → report → publish to `health-reports` → if failing: agent → PR |
| `ci` | Every push and PR | DB matches migrations → tests |

## Demo script (about 5 minutes)

1. **The problem.** Open the [People page](https://harness-demo-beige.vercel.app/) and click **Load 5000 people**: a couple of seconds and **5,001 DB queries**.
   Look up person **15000** on the Person page: **HTTP 500**.
2. **Sensors.** Run **health-check**. Show [`/health.html`](https://harness-demo-beige.vercel.app/health.html): **4 of 4 failing**.
3. **Agent.** The Gemini agent opens a PR. Each change maps to a failing check.
4. **Human approval.** Merge. Vercel deploys.
5. **Green.** Click **Load 5000 people** again: 1 query, fast. Run **health-check**: **all checks pass**.

## Resetting the demo

```bash
bash scripts/demo_reset.sh
```

Opens a PR that restores `app/`, `api/`, `tests/`, `migrations/`, `public/`, `requirements.txt` and `data/` to the `demo-start` tag.

## Project layout

```
harness-demo/
├── api/index.py              FastAPI app + middleware (Vercel entry point)
├── app/
│   ├── routes.py*            The three endpoints
│   └── db.py                 SQLite access, query counting, slow-query log
├── public/                   index.html  person.html  health.html  architecture.html  css/  js/ (legacy-charts.js*)
├── migrations/001_init.sql   people table
├── data/shop.db              Seeded database (committed)
├── tests/test_api.py         API tests
├── scripts/                  run_sensors.sh  collect_runtime.py  build_report.py  agent.py
│                             publish_report.sh  build_db.py  demo_reset.sh
├── budgets.json              What "healthy" means
├── requirements.txt*         App dependencies (Vercel installs these)
├── requirements-dev.txt      uvicorn, httpx, pytest, vulture
└── .github/workflows/        health-check.yml  ci.yml
                              * contains a planted problem
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Agent skipped: "GEMINI_API_KEY is not set" | `gh secret set GEMINI_API_KEY` |
| `Gemini API error 429` | Free-tier rate limit. Wait a minute and run again. |
| Agent prints "Giving up" | Neither attempt passed the tests. Run again (answers vary). |
| `/health.html` says "No report yet" | Run **health-check** once |
| Runtime checks show "local (CI)" | The `APP_URL` repo variable is missing |
| `/api/*` returns 404 on Vercel | Don't add rewrites to `vercel.json` |
| `ci` fails with "does not match migrations" | `python scripts/build_db.py` and commit `data/shop.db` |
