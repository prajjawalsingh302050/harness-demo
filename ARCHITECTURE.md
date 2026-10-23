# Architecture

How the harness demo is put together: the app, the sensors, the report, the coding agent and the delivery loop.
For setup and the demo script, see [README.md](README.md).

## 1. System overview

```
                    ┌────────────────────────── Vercel ───────────────────────────┐
   Browser ───────► │  CDN: public/*.html, css, js                                 │
                    │  Python function: api/index.py ─► app/routes.py ─► app/db.py │
                    │                                    ─► data/shop.db (SQLite)  │
                    └───────────────▲──────────────────────────────────▲──────────┘
                                    │ load test (APP_URL)              │ deploy on push / PR preview
   ┌──────────────────────── GitHub Actions: health-check ─────────────┴──────────────┐
   │ run_sensors.sh ─► build_report.py ─► publish_report.sh ─► agent.py ─► gh pr create │
   └───────┬───────────────────────────────┬─────────────────────────────────┬─────────┘
           ▼                               ▼                                 ▼
     job summary              health-reports branch → /health.html     human reviews + merges
```

Three independent parts:

1. **The app** runs on Vercel. It knows nothing about the harness except that it exposes timing headers.
2. **The sensors and report** run in GitHub Actions or locally. They only read the code and HTTP responses.
3. **The agent** runs after the report and can only change application files. Everything goes through a PR.

## 2. Database

| Table | Rows | Columns | Indexes |
|---|---|---|---|
| `people` | 10,000 | id, name, email, city | primary key on `id` only (**no index on `email`**) |

`scripts/build_db.py` applies `migrations/*.sql` in name order, then seeds with `random.Random(42)`.
`--check` compares schema and row counts with the committed `data/shop.db`.
The app opens it with `mode=ro&immutable=1`: read-only and lock-free, safe for many serverless instances.

## 3. Backend

Three files, no layers:

| File | Role |
|---|---|
| `api/index.py` | Creates the FastAPI app (docs at `/api/docs`), the `timing_headers` middleware and includes the router. Serves `public/` locally (skipped on Vercel, where the `VERCEL` env var is set). |
| `app/routes.py` | `GET /api/people?limit=N`, `GET /api/people/{id}`, `GET /api/health` |
| `app/db.py` | `connect()` and `query()`. A contextvar holds per-request counters; `query()` counts and times every statement and logs `slow query` over 5 ms. |

### Request flow (planted state)

```
GET /api/people?limit=5000
  └─ timing_headers middleware: start per-request stats
      └─ routes.list_people(limit=5000)
          ├─ connect()
          ├─ query("SELECT email FROM people ORDER BY id LIMIT 5000")       1 query
          └─ for each email:  find_by_email()                               5,000 queries
                query("SELECT … FROM people WHERE email = ?")              full table scan each time
  └─ middleware: X-DB-Queries: 5001 ; Server-Timing: db;dur=…, app;dur=…
```

The fix is one query: `SELECT id, name, email, city FROM people ORDER BY id LIMIT ?`.

## 4. Sensors

`scripts/run_sensors.sh` runs everything and writes raw outputs to `reports/`:

| Step | Command | Output |
|---|---|---|
| Dead code | `vulture app api --min-confidence 60 --ignore-decorators "@router.*,@app.*" --ignore-names row_factory` | `vulture.txt` |
| Local runtime | start `uvicorn` with logs to `app.log`, then `collect_runtime.py` against it | `runtime-local.json`, `app.log` |
| Live runtime | `collect_runtime.py --base-url $APP_URL` (if set) | `runtime-live.json` |
| Report | `build_report.py` (also runs the unused-libraries check) | `health-report.json`, `health-report.md` |

### Load test (`collect_runtime.py`)

- `asyncio` + `httpx`, 15–20 seconds, fixed seeds, 5 concurrent workers:
  - 2 **heavy** workers keep requesting `/api/people?limit=5000` (the "Load 5000 people" button).
  - 3 **light** workers request `/api/people/{id}` (every 5th lookup uses an ID that doesn't exist) and `/api/health` (15%).
  Keeping them separate means slow heavy requests can't starve the lookups, so the error rate is reliable even when "Load 5000" takes 10+ seconds.
- Three warm-up requests first. A dropped keep-alive connection is retried once (the server closes the connection after a 500).
- Records latency, status, `X-DB-Queries` and `Server-Timing db`, then summarises p50/p95, average queries and 5xx per endpoint.

### Check logic (`build_report.py`)

| Check | Logic |
|---|---|
| Dead code | vulture findings + `public/js/*.js` files not referenced as `/js/<name>` in any HTML |
| Unused libraries | Each package in `requirements.txt` (mapped to its import name, e.g. `python-dateutil` → `dateutil`) must be imported somewhere in `app/` or `api/` |
| Latency | p95 of `/api/people?limit=5000` ≤ budget, live numbers preferred. Evidence: average queries per request, and `EXPLAIN QUERY PLAN` for the most frequent slow queries; a filtered query whose plan is `SCAN <table>` is marked `FULL TABLE SCAN` |
| Error rate | 5xx (or connection failure) percentage ≤ budget |

Each check carries `details` (evidence), `files` (where to look) and `hint` (direction, not a solution).
`publish_report.sh` copies the report to `latest.json` on the `health-reports` branch and appends to `history.json` (last 100 runs).

## 5. Coding agent

```
health-report.md + source files ──► Gemini (JSON schema output) ──► apply allowed changes
                                                                         │
                                          ┌──── rebuild DB + pytest ◄────┘
                                          │ fail                 │ pass
                                          ▼                      ▼
                           roll back, send error, retry once    write pr-title.txt / pr-body.md
```

| Design choice | Reason |
|---|---|
| Plain REST call with `urllib`, no SDK | One less dependency; easy to read |
| Model auto-selection (newest stable "flash") | Free-tier model names change; `GEMINI_MODEL` pins one |
| `responseSchema` with full-file writes | Reliable to parse; no fragile diff application |
| Path allowlist + protected `001_init.sql` | The agent can't weaken the harness (workflows, scripts, budgets) |
| Verify before PR, one retry with the error | Only working change sets reach a human |

## 6. Delivery loop

| Event | What happens |
|---|---|
| `workflow_dispatch` or daily cron (02:30 UTC) | `health-check` runs sensors; if anything fails and the key is set, the agent opens a PR |
| PR opened | Vercel builds a preview deployment |
| Merge to `main` | Vercel deploys to production; `ci` runs the DB check and tests |
| Next `health-check` | Measures the new production deployment; green report, no PR |

## 7. Guardrails

| Guardrail | Where |
|---|---|
| Budgets decide "healthy", not the model | `budgets.json`, `build_report.py` |
| The agent can only edit application files | `EDITABLE`, `PROTECTED` in `agent.py` |
| Every change set is verified before a PR | `verify()` in `agent.py` |
| The agent never merges or pushes to `main` | The workflow opens a PR; a human merges |
| Secrets stay out of the repo | `.env` git-ignored; `GEMINI_API_KEY` is a GitHub secret |
| The planted state is recoverable | `demo-start` tag + `demo_reset.sh` |

## 8. Known limitations

- **Only four sensors.** The article also shows dependabot, coverage quality, availability, log anomalies and response-quality sampling. They are left out to keep the demo short.
- **The unused-library check is import-based.** A package used only at runtime (a plugin, a CLI) would be reported; add it to `IMPORT_NAMES` or handle it explicitly.
- **Slow-query evidence comes from the local log**, because reading Vercel's runtime logs would need a Vercel token.
- **Agent output varies.** Verification and the retry make failures safe, not impossible.
- **`ci` doesn't run on agent PRs** (GitHub doesn't trigger workflows from `GITHUB_TOKEN` events). The agent runs the same checks itself.
