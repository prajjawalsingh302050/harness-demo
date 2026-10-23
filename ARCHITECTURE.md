# Architecture

How the harness demo is put together: the app, the sensors, the report, the coding agent and the delivery loop.
For setup and the demo script, see [README.md](README.md).

## 1. System overview

```
                    ┌──────────────────────────── Vercel ─────────────────────────────┐
   Browser ───────► │  CDN: public/*.html, css, js                                     │
                    │  Python function (FastAPI preset): api/index.py ─► app/ ─► SQLite │
                    └───────────────▲───────────────────────────────────────▲─────────┘
                                    │ load test (APP_URL)                   │ deploy on push / PR preview
                                    │                                       │
   ┌──────────────────────── GitHub Actions: health-check ──────────────────┴──────────┐
   │ run_sensors.sh ─► build_report.py ─► publish_report.sh ─► agent.py ─► gh pr create │
   └───────┬───────────────────────────────┬─────────────────────────────────┬─────────┘
           │ reports/ (artifact)           │ health-reports branch           │ PR (label harness-agent)
           ▼                               ▼                                 ▼
     job summary                     /health.html reads it              human reviews + merges
```

There are three independent parts:

1. **The app** (frontend + backend) runs on Vercel. It knows nothing about the harness except that it exposes timing headers.
2. **The sensors and report** run in GitHub Actions or locally. They only read the code, the database and HTTP responses.
3. **The agent** runs after the report and can only change application files. Everything it produces goes through a PR.

## 2. Frontend

- Static HTML pages with one script each, plus two shared scripts (`api.js`, `config.js`). No framework or bundler.
- `apiGet(path)` in `js/api.js` measures the round trip with `performance.now()` and reads `X-DB-Queries`,
  so every page shows response time, query count and status. That makes the N+1 problem visible to the audience.
- `health.html` fetches `latest.json` and `history.json` from the `health-reports` branch through
  `https://api.github.com/repos/<owner>/<repo>/contents/<file>?ref=health-reports` with
  `Accept: application/vnd.github.raw+json`. The contents API is used because raw.githubusercontent.com caches for minutes.
  Unauthenticated calls are limited to 60 per hour per IP, which is plenty for a demo.
- Locally, FastAPI mounts `public/` at `/` (`StaticFiles(html=True)`). On Vercel the `VERCEL` environment variable is set,
  so the mount is skipped and the CDN serves the files.

## 3. Backend

### Request flow

```
GET /api/orders?page=2
  └─ timing_headers middleware: start per-request stats (contextvar)
      └─ orders.list_orders()
          ├─ connect()                       sqlite3, file:data/shop.db?mode=ro&immutable=1
          ├─ query(... orders page ...)      counted, timed, logged if > 5 ms
          ├─ for each order:                 (planted N+1)
          │    query(users by id)
          │    query(SUM over order_items)   full scan without the index
          └─ price_with_tax()                tax by city
  └─ middleware: Server-Timing: db;dur=…, app;dur=… ; X-DB-Queries: 101
```

### Why SQLite

- It is bundled with the function, so there is no external database account or network hop, and the demo is reproducible.
- `EXPLAIN QUERY PLAN` shows the planted problem clearly (`SCAN order_items` → `SEARCH … USING INDEX`).
- It is opened read-only and `immutable`, which is safe for many concurrent serverless instances.
- The trade-off: the app cannot write. That is fine for a read-only dashboard.

### Data model

| Table | Rows | Columns | Indexes (planted state) |
|---|---|---|---|
| `users` | 2,000 | id, name, email, city | primary key |
| `orders` | 20,000 | id, user_id, created_at, status | primary key, `created_at` |
| `order_items` | 160,156 | id, order_id, product, qty, unit_price | primary key only (**no `order_id` index**) |

`scripts/build_db.py` applies `migrations/*.sql` in name order, then seeds with `random.Random(42)`,
so every build has the same rows. `--check` compares schema and row counts (not bytes, because SQLite
writes its version into the file header) to make sure the committed DB matches the migrations.

## 4. Sensors

Three sensors, one per box we kept from the article's diagram:

| Diagram half | Sensor | Kind |
|---|---|---|
| Continuous drift detection | Dead code | 🟥 inferential |
| Continuous runtime feedback | p95 latency `/api/orders` | 🟦 computational |
| Continuous runtime feedback | Error rate (HTTP 5xx) | 🟦 computational |

`scripts/run_sensors.sh` runs them in a fixed order and writes raw outputs to `reports/`:

| Step | Command | Output |
|---|---|---|
| Dead code | `vulture app api --min-confidence 60 --ignore-decorators "@router.*,@app.*" --ignore-names row_factory` | `vulture.txt` |
| Local runtime | start `uvicorn api.index:app` with logs to `app.log`, then `collect_runtime.py` against it | `runtime-local.json`, `app.log` |
| Live runtime | `collect_runtime.py --base-url $APP_URL` (if set) | `runtime-live.json` |
| Report | `build_report.py` | `health-report.json`, `health-report.md` |

### Load test (`collect_runtime.py`)

- `asyncio` + `httpx`, 4 concurrent workers, 15–20 seconds, fixed random seeds (repeatable).
- Request mix: 50% `/api/orders?page=1..20`, 40% `/api/users/{id}` (20% of those use IDs that don't exist), 10% `/api/health`.
- Three warm-up requests first, so Vercel cold starts don't distort p95.
- Records latency, status, `X-DB-Queries` and `Server-Timing db` for every request, then summarises p50 and p95,
  average queries, 5xx count per endpoint, and the overall error rate.

### How each check decides pass or fail (`build_report.py`)

| Check | Logic |
|---|---|
| Dead code | vulture findings + `public/js/*.js` files not referenced as `/js/<name>` in any HTML; fail if count > budget |
| Latency | p95 of `/api/orders` ≤ budget, live numbers preferred. Evidence attached: average `X-DB-Queries` per request, and `EXPLAIN QUERY PLAN` for the most frequent `slow query` log lines, marked `FULL TABLE SCAN` when a plan line is `SCAN <real table>` without `INDEX` |
| Error rate | 5xx (or connection failure) percentage ≤ budget |

Each check in the JSON carries `details` (evidence), `files` (where to look) and `hint` (direction, not a solution).
These three fields are what make the agent's job tractable.

### Report schema

```jsonc
{
  "generated_at": "2026-10-23T16:04:39+00:00",
  "commit": "f42db7b",
  "healthy": false,
  "failed": 3,
  "checks": [
    {
      "id": "latency_orders",
      "name": "p95 latency /api/orders [live (Vercel)]",
      "kind": "computational",          // or "inferential"
      "area": "runtime",                // or "codebase"
      "value": "1734 ms",
      "budget": "500 ms",
      "ok": false,
      "details": ["Each page of 50 orders runs 101.0 DB queries on average …",
                  "5372x slow query FULL TABLE SCAN: SELECT SUM(qty * unit_price) … -> plan: SCAN order_items"],
      "files": ["app/routes/orders.py", "migrations/"],
      "hint": "Find where the time goes. If one request runs a query per order (N+1) …"
    }
  ]
}
```

`publish_report.sh` copies this to `latest.json` on the orphan `health-reports` branch and appends
`{generated_at, commit, healthy, failed}` to `history.json` (last 100 runs).

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
| Plain REST call with `urllib`, no SDK | One less dependency; easy to read in a demo |
| Model auto-selection (newest stable "flash") | Free-tier model names change; `GEMINI_MODEL` pins one |
| `responseSchema` with full-file writes | Structured output is reliable to parse; full files avoid fragile diff application |
| Path allowlist + protected `001_init.sql` | The agent can't weaken the harness (workflows, scripts, budgets) or rewrite history |
| Verify before PR, one retry with the error | Only working change sets reach a human |
| Rules in the system prompt | Keep API shapes, no catch-all handlers, no deleting tests, fix causes not symptoms |

The prompt contains the report (with evidence, files and hints) and every file in `app/`, `api/`, `tests/`,
`migrations/`, `public/` and `requirements.txt`. The whole repo is small enough to fit comfortably.

## 6. Delivery loop and CI/CD

| Event | What happens |
|---|---|
| `workflow_dispatch` or daily cron (02:30 UTC = 08:00 IST) | `health-check` runs sensors; if anything fails and the key is set, the agent opens a PR |
| PR opened | Vercel builds a preview deployment (Vercel GitHub app) |
| Push to `main` (merge) | Vercel deploys to production; `ci` runs the DB check and tests |
| Next `health-check` | Measures the new production deployment; publishes a green report; no PR |

The workflow has `contents: write` (to publish reports and push the agent branch) and `pull-requests: write`.
`concurrency: health-check` prevents two runs overlapping.

## 7. Guardrails summary

| Guardrail | Where |
|---|---|
| Budgets decide "healthy", not the model | `budgets.json`, `build_report.py` |
| The agent can only edit application files | `EDITABLE`, `PROTECTED` in `agent.py` |
| Every change set is verified before a PR | `verify()` in `agent.py` |
| The agent never merges or pushes to `main` | Workflow opens a PR; a human merges |
| Secrets stay out of the repo | `.env` git-ignored; `GEMINI_API_KEY` is a GitHub secret |
| The planted state is recoverable | `demo-start` tag + `demo_reset.sh` |

## 8. Known limitations

- **Only three sensors.** The article's diagram also shows dependabot, coverage quality, availability, log anomalies
  and response-quality sampling. They are left out to keep the demo short; each would be one more function in `build_report.py`.
- **Slow-query evidence comes from the local log.** The `EXPLAIN` details on the latency check use the local server's log in CI,
  because reading Vercel's runtime logs would need a Vercel token. The code is identical, so the signal is the same.
- **Agent output varies.** The same report can give different fixes. Verification and the retry make failures safe, not impossible.
- **`ci` doesn't run on agent PRs** (GitHub doesn't trigger workflows from `GITHUB_TOKEN` events). The agent runs the same checks itself.
- **The repo grows by about 5 MB per fix cycle**, because the rebuilt `data/shop.db` is committed.
