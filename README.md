# Harness Demo: continuous drift and health sensors

A working demo of the **"continuous drift and health sensors"** idea from Martin Fowler's article
[Harness Engineering](https://martinfowler.com/articles/harness-engineering.html).

A small shop app ships with **planted problems** in its code and its runtime behaviour.
A GitHub Action runs **three sensors** (one on the codebase, two on the live deployment), builds a
**health report**, and a **Gemini coding agent** fixes what fails and opens a **pull request**.
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
   │  drift detection        runtime feedback (local + live)      │
   │  dead code              p95 latency · error rate             │
   │  (vulture + JS scan)    (load test)                          │
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

## Contents

1. [What the demo shows](#what-the-demo-shows)
2. [Tech stack](#tech-stack)
3. [Frontend](#frontend)
4. [Backend](#backend)
5. [Sensors and budgets](#sensors-and-budgets)
6. [The coding agent](#the-coding-agent)
7. [Planted problems](#planted-problems)
8. [Setup](#setup)
9. [Running locally](#running-locally)
10. [Running the loop in GitHub](#running-the-loop-in-github)
11. [Demo script](#demo-script)
12. [Resetting the demo](#resetting-the-demo)
13. [Project layout](#project-layout)
14. [Troubleshooting](#troubleshooting)

---

## What the demo shows

The article's diagram has two halves. This repo implements both with a deliberately small set of sensors:

| Diagram half | What it means | Sensor here |
|---|---|---|
| **Continuous drift detection** (codebase) | Problems that build up slowly in the code | **Dead code**: `vulture` + a scan for JS files no page loads |
| **Continuous runtime feedback** (runtime) | Signals from the running system | **p95 latency** and **error rate**, from a load test against the live app |

The article's diagram lists more sensors (dependabot, code-coverage quality, availability, log anomalies,
response-quality sampling). They are left out on purpose so the loop is easy to follow in a short demo.

Each sensor is labelled like the diagram's legend:

- 🟦 **Computational**: a deterministic tool. Same input, same answer.
- 🟥 **Inferential**: needs judgement. A tool produces evidence and the coding agent decides what it means.

**"Healthy" is defined by numbers in [`budgets.json`](budgets.json), not by the AI.**

## Tech stack

| Layer | Technology | Hosted on |
|---|---|---|
| Frontend | HTML, CSS, JavaScript (no framework, no build step) | Vercel CDN (`public/`) |
| Backend | FastAPI, Python 3.12 | One Vercel Python function (FastAPI preset) |
| Database | SQLite (`data/shop.db`, read-only, about 5 MB) | Bundled with the function |
| Sensors | vulture, httpx load test | GitHub Actions |
| Coding agent | Gemini API (free tier, newest stable "flash" model) | GitHub Actions |
| Reports | JSON on the `health-reports` branch | GitHub, read by `/health.html` |

## Frontend

Plain static files in `public/`. Vercel serves them from its CDN; locally, FastAPI serves them.

| Page | Purpose |
|---|---|
| `index.html` | Orders dashboard: 50 orders per page, with response time, DB query count and HTTP status shown as pills |
| `user.html` | Customer lookup by ID (`5000` shows the planted HTTP 500) |
| `health.html` | Latest health report and a red/green history of every run |
| `architecture.html` | "How it works": the loop, frontend and backend setup, sensors, planted problems, and live API calls |

| Script | Purpose |
|---|---|
| `js/api.js` | `apiGet()` wraps `fetch` and reads the `X-DB-Queries` header and response time; `renderMetrics()` draws the pills |
| `js/app.js` | Orders table and paging |
| `js/user.js` | Customer lookup |
| `js/health.js` | Reads `latest.json` and `history.json` from the `health-reports` branch through the GitHub contents API (not cached, unlike raw.githubusercontent.com) |
| `js/architecture.js` | Live API buttons on the How it works page |
| `js/config.js` | Repository owner and name used by the pages |
| `js/legacy-charts.js` | **Planted dead code.** No page loads it. |

Styling is a single `css/style.css` with light and dark mode via `prefers-color-scheme`.

## Backend

| Item | Details |
|---|---|
| Entry point | `api/index.py` imports `app` from `app/main.py`, where `create_app()` sets up logging, middleware, the router registry and (locally) the static UI |
| Layers | **routes** (HTTP only) → **service registry** → **services** (business logic) → **repositories** (SQL) → **db** |
| Router registry | `app/api/router.py`: every route module is listed in `ROUTERS` and mounted under `/api` |
| Service registry | `app/services/registry.py`: `ServiceRegistry(con)` builds repositories and services lazily, once per request. Routes get it with `Depends(get_services)` (`app/api/deps.py`) |
| Routes | `app/api/routes/orders.py` `GET /api/orders?page=N` · `users.py` `GET /api/users/{id}` · `health.py` `GET /api/health` |
| Services | `OrderService`, `UserService`, `HealthService` in `app/services/`, plus `pricing.py` (tax by city) |
| Repositories | `app/repositories/orders.py`, `users.py`: every SQL statement lives here |
| Schemas | `app/schemas/`: Pydantic response models (`response_model=`), the contract the UI depends on |
| Data access | `app/db/`: `connect()` opens SQLite read-only (`mode=ro&immutable=1`); `query()` runs SQL, counts queries per request and logs `slow query` for anything over 5 ms |
| Config | `app/core/config.py`: one `Settings` object (DB path, slow-query threshold, page size, log level) |
| API docs | Swagger UI at `/api/docs` |
| Observability | Every response gets `Server-Timing: db;dur=…, app;dur=…` and `X-DB-Queries: N`. The sensors and the UI both read these. |
| Schema | `migrations/*.sql`, applied in order by `scripts/build_db.py`, which also seeds deterministic data (2,000 users, 20,000 orders, 160,156 order items) |

Backend layout:

```
api/index.py                  Vercel entry point: imports `app` from app.main
app/
├── main.py                   create_app(): logging, middleware, router registry, static UI (local only)
├── core/
│   ├── config.py             Settings (DB path, slow-query threshold, page size, ...) read once from env
│   ├── logging.py            Log format and level
│   └── middleware.py         Server-Timing + X-DB-Queries headers
├── api/
│   ├── router.py             Router registry: ROUTERS list, all mounted under /api
│   ├── deps.py               Per-request dependencies: get_db() → get_services()
│   └── routes/               orders.py  users.py  health.py   (HTTP only, no logic, no SQL)
├── services/
│   ├── registry.py           ServiceRegistry: wires repositories into services, per request
│   ├── orders.py             OrderService: orders page, customer, taxed total
│   ├── users.py              UserService: customer + order count
│   ├── health.py             HealthService: DB ping
│   ├── pricing.py            Tax by city
│   └── legacy_discount.py    (planted dead code)
├── repositories/             orders.py  users.py   (every SQL statement, via app.db.query)
├── schemas/                  Pydantic response models = the API contract
└── db/                       connect(), query(): read-only SQLite, query counting, slow-query log
```

To add an endpoint: a repository method for the SQL, a service method for the logic, a route in
`app/api/routes/`, register the service in `ServiceRegistry` and the router in `ROUTERS`.

API responses:

```jsonc
// GET /api/orders?page=1
{ "page": 1, "page_size": 50,
  "orders": [ { "id": 6939, "customer": "Ishaan Mehta", "city": "Jaipur",
                "created_at": "2026-10-17 23:48:00", "status": "cancelled", "total": 31019.84 } ] }

// GET /api/users/1
{ "id": 1, "name": "…", "email": "…@example.com", "city": "…", "order_count": 12 }

// GET /api/health
{ "status": "ok" }
```

## Sensors and budgets

All sensors run through [`scripts/run_sensors.sh`](scripts/run_sensors.sh), in GitHub Actions and locally.

| # | Check | Tool | Kind | Area | Budget |
|---|---|---|---|---|---|
| 1 | Dead code | `vulture` + a scan for JS files no HTML page loads | 🟥 | codebase | 0 items |
| 2 | p95 latency `/api/orders` | load test (`scripts/collect_runtime.py`) | 🟦 | runtime | 500 ms |
| 3 | Error rate (HTTP 5xx) | load test (20% of customer lookups use IDs that don't exist) | 🟦 | runtime | ≤ 1% |

Runtime checks use the **live Vercel deployment** when `APP_URL` is set, and the local server otherwise.

The latency check also collects **evidence** for the agent: the average `X-DB-Queries` per request (shows the N+1 loop)
and `EXPLAIN QUERY PLAN` for the most frequent `slow query` lines in the local server log (shows the full table scan).
These are details of the latency check, not separate pass/fail checks.

Outputs (in `reports/`, git-ignored):

| File | Content |
|---|---|
| `health-report.json` | Every check: id, name, kind, area, value, budget, ok, details, files, hint |
| `health-report.md` | Human-readable table plus failing-check details. Also the agent's input. |
| `vulture.txt` | Raw vulture output |
| `runtime-local.json`, `runtime-live.json` | Load-test summaries |
| `app.log` | Local server log (slow queries) |

## The coding agent

[`scripts/agent.py`](scripts/agent.py) is about 250 lines with no SDK dependency; it calls the Gemini REST API directly.

1. Reads `reports/health-report.md` and the relevant source files.
2. Picks a model: `GEMINI_MODEL` if set, otherwise the newest stable Gemini "flash" model available to your key.
3. Asks for a JSON answer (`pr_title`, `pr_body`, and a list of full-file `write` or `delete` changes).
4. Applies only changes inside `app/`, `api/`, `tests/`, `migrations/`, `public/` and `requirements.txt`.
   Everything else is rejected, including `001_init.sql`, workflows, scripts and budgets.
5. **Verifies**: rebuilds `data/shop.db` from the migrations and runs the test suite.
6. If verification fails, it rolls back, sends the error to Gemini, and tries once more.
7. On success it writes `reports/pr-title.txt` and `reports/pr-body.md`. The workflow then opens the PR.

The agent never pushes to `main`. A human reviews and merges.

## Planted problems

| # | Problem | Where | Sensor that finds it | Expected fix |
|---|---|---|---|---|
| 1 | Unused module `legacy_discount.py`, unused `old_tax_rate()`, unused `import json` | `app/` | dead code (vulture) | Delete |
| 2 | `legacy-charts.js` is never loaded | `public/js/` | dead code (JS scan) | Delete |
| 3 | N+1: one query per order for the customer and another for the total (101 per page) | `app/services/orders.py`, `app/repositories/orders.py` | p95 latency | One repository query with a JOIN |
| 4 | No index on `order_items.order_id`, so every total is a full table scan | `migrations/001_init.sql` | p95 latency (EXPLAIN evidence) | New migration `002_*.sql` with `CREATE INDEX` |
| 5 | `None["id"]` crash for a missing customer → HTTP 500 | `app/services/users.py` | error rate | Return HTTP 404 |

Measured before and after the fixes:

| | Planted | Fixed |
|---|---|---|
| `/api/orders` p95 (local) | ~600 ms | ~17 ms |
| `/api/orders` p95 (live Vercel) | ~1,700 ms | under 500 ms |
| DB queries per orders page | 101 | 1 |
| Error rate | ~12% | 0% |
| Checks passing | 0 / 3 | 3 / 3 |

## Setup

### 1. Gemini API key (free)

1. Open <https://aistudio.google.com/apikey> and sign in.
2. **Create API key** and copy it.
3. Local: `cp .env.example .env` and set `GEMINI_API_KEY=…`. `.env` is git-ignored.
4. GitHub: `gh secret set GEMINI_API_KEY --repo prajjawalsingh302050/harness-demo` and paste the key.

On the free tier, Google may use prompts to improve its products. This repo contains only fake data.

### 2. GitHub repository settings (already done for this repo)

- **Settings → Actions → General → Workflow permissions:** "Read and write" and "Allow GitHub Actions to create and approve pull requests".
- **Variables:** `APP_URL` = the production URL. Optional `GEMINI_MODEL` to pin a model.
- **Secret:** `GEMINI_API_KEY`.

### 3. Vercel (already done for this repo)

The project is linked to this GitHub repo: every push to `main` deploys to production, and every PR gets a preview URL.
Vercel detects FastAPI automatically, so `vercel.json` needs no routes. `.vercelignore` keeps tests, scripts and reports out of the deployment.

## Running locally

```bash
# 1. Environment
uv venv .venv --python 3.12
uv pip install -p .venv -r requirements.txt -r requirements-dev.txt

# 2. App (UI + API) on http://127.0.0.1:8000
.venv/bin/uvicorn api.index:app --reload

# 3. Sensors → reports/health-report.md
PYTHON=.venv/bin/python bash scripts/run_sensors.sh
#    add APP_URL=https://harness-demo-beige.vercel.app to also measure the live app

# 4. Coding agent (edits your working tree)
.venv/bin/python scripts/agent.py

# 5. Sensors again: should be all green
PYTHON=.venv/bin/python bash scripts/run_sensors.sh
```

Other commands:

| Command | What it does |
|---|---|
| `.venv/bin/python scripts/build_db.py` | Rebuild `data/shop.db` from `migrations/` |
| `.venv/bin/python scripts/build_db.py --check` | Fail if the committed DB doesn't match the migrations (CI runs this) |
| `.venv/bin/python -m pytest -q` | Run tests |
| `git restore . && git clean -fd app tests migrations public` | Undo a local agent run |

## Running the loop in GitHub

Two workflows:

| Workflow | Trigger | Steps |
|---|---|---|
| `health-check` | Manual (**Actions → health-check → Run workflow**) and daily at 08:00 IST | Install → run sensors (local + live) → build report → publish to `health-reports` branch → upload artifacts → if failing: Gemini agent → open PR |
| `ci` | Every push and PR | Check DB matches migrations → run tests |

The run's **Summary** tab shows the full health report. A PR opened by the agent carries the label `harness-agent`.

PRs opened with the workflow's built-in token do not trigger other workflows (a GitHub rule), so `ci` does not run on agent PRs.
The agent runs the same checks itself before opening the PR, and Vercel still builds a preview.

## Demo script

About 5 minutes.

1. **The problem.** Open the [Orders page](https://harness-demo-beige.vercel.app/): about 1–2 s and **101 DB queries**.
   Look up customer **5000** on the Customers page: **HTTP 500**.
2. **Sensors.** Run **health-check**. Show the job summary or [`/health.html`](https://harness-demo-beige.vercel.app/health.html): **3 of 3 checks failing**: dead code 🟥, latency 🟦, error rate 🟦.
3. **Agent.** The Gemini agent opens a PR. Walk through it: each change maps to a failing check, with the evidence in the description.
4. **Preview.** Open the Vercel preview link on the PR: the Orders page is fast, with 1 DB query.
5. **Human approval.** Merge the PR. Vercel deploys to production.
6. **Green.** Run **health-check** again: **all checks pass** and no PR is opened. `/health.html` history goes red → green.
7. **Guardrails** (optional): show `budgets.json`, the agent's allowed paths, and that it rebuilds the DB and runs the tests before any PR.

## Resetting the demo

```bash
bash scripts/demo_reset.sh
```

This opens a PR that restores `app/`, `api/`, `tests/`, `migrations/`, `public/`, `requirements.txt` and `data/` to the `demo-start` tag, which re-plants every problem.
Merge it, wait for Vercel, and the demo is ready to run again.

## Project layout

```
harness-demo/
├── public/                     Frontend (static)
│   ├── index.html  user.html  health.html  architecture.html
│   ├── css/style.css
│   └── js/  api.js  app.js  user.js  health.js  architecture.js  config.js  legacy-charts.js*
├── api/index.py                FastAPI entry point (Vercel function)
├── app/
│   ├── main.py                 App factory
│   ├── core/                   config.py  logging.py  middleware.py
│   ├── api/                    router.py (router registry)  deps.py  routes/orders.py*  users.py  health.py
│   ├── services/               registry.py  orders.py*  users.py*  health.py  pricing.py*  legacy_discount.py*
│   ├── repositories/           orders.py  users.py
│   ├── schemas/                Pydantic response models
│   └── db/                     SQLite access, query counting, slow-query log
├── migrations/001_init.sql*    Schema (built into data/shop.db)
├── data/shop.db                Seeded database (committed)
├── tests/test_api.py           API tests
├── scripts/
│   ├── run_sensors.sh          Run the three sensors and build the report
│   ├── collect_runtime.py      Load test and runtime metrics
│   ├── build_report.py         Combine sensors, apply budgets → JSON + Markdown
│   ├── agent.py                Gemini coding agent
│   ├── publish_report.sh       Push the report to the health-reports branch
│   ├── build_db.py             Build or check data/shop.db
│   └── demo_reset.sh           Re-plant the problems through a PR
├── budgets.json                What "healthy" means
├── requirements.txt           App dependencies (Vercel installs these)
├── requirements-dev.txt        Local server, load test, test and dead-code tools
├── .github/workflows/          health-check.yml  ci.yml
├── vercel.json  .vercelignore  .python-version  .env.example
├── README.md  ARCHITECTURE.md  CLAUDE.md
                                * contains a planted problem
```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Agent step skipped with "GEMINI_API_KEY is not set" | Add the repo secret: `gh secret set GEMINI_API_KEY` |
| `Gemini API error 429` | Free-tier rate limit. Wait a minute and run again. |
| `No Gemini 'flash' model…` | Set the `GEMINI_MODEL` repo variable or `.env` value to a model listed in AI Studio |
| Agent prints "Giving up" | Neither attempt passed the tests. Check the run log for the test failure and run again (answers vary). |
| `gh pr create` fails with "not permitted" | Enable "Allow GitHub Actions to create and approve pull requests" (Settings → Actions → General) |
| `/health.html` says "No report yet" | Run **health-check** once. The page reads the `health-reports` branch. |
| Runtime checks show "local (CI)" | The `APP_URL` repo variable is missing |
| `/api/*` returns 404 on Vercel | Don't add rewrites to `vercel.json`; the FastAPI preset routes `/api/*` to the app itself |
| `ci` fails with "does not match migrations" | Run `python scripts/build_db.py` and commit `data/shop.db` |
