"""FastAPI entry point. Vercel serves this as a Python function; locally run:
    uvicorn api.index:app --reload
"""
import logging
import os
import sys
import time
from pathlib import Path

# Project root. Added to the import path so `import app...` works when Vercel runs this file.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Request  # noqa: E402

from app.db import start_request_stats  # noqa: E402
from app.routes import router  # noqa: E402

# Log format, e.g. "WARNING app.db slow query 7.4ms: SELECT ...". The sensors search for these lines.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

# API docs live under /api/ because Vercel only sends /api/* requests to this function.
app = FastAPI(title="Harness Demo", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)


@app.middleware("http")
async def timing_headers(request: Request, call_next):
    """Time every request and add two headers that the UI and the runtime sensors read.

    X-DB-Queries: how many SQL queries the request ran.
    Server-Timing: milliseconds spent in the database and in total.
    """
    stats = start_request_stats()
    started = time.perf_counter()
    response = await call_next(request)
    total_ms = (time.perf_counter() - started) * 1000
    response.headers["Server-Timing"] = f"db;dur={stats['ms']:.1f}, app;dur={total_ms:.1f}"
    response.headers["X-DB-Queries"] = str(stats["queries"])
    return response


# Register the endpoints from app/routes.py.
app.include_router(router)

# On Vercel the static UI is served from public/; locally FastAPI serves it.
if not os.environ.get("VERCEL"):
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=ROOT / "public", html=True), name="public")
