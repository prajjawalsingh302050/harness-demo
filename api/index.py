"""FastAPI entry point. Vercel serves this as a Python function; locally run:
    uvicorn api.index:app --reload
"""
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Request  # noqa: E402

from app.db import start_request_stats  # noqa: E402
from app.routes import router  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

app = FastAPI(title="Harness Demo", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)


@app.middleware("http")
async def timing_headers(request: Request, call_next):
    stats = start_request_stats()
    started = time.perf_counter()
    response = await call_next(request)
    total_ms = (time.perf_counter() - started) * 1000
    response.headers["Server-Timing"] = f"db;dur={stats['ms']:.1f}, app;dur={total_ms:.1f}"
    response.headers["X-DB-Queries"] = str(stats["queries"])
    return response


app.include_router(router)

# On Vercel the static UI is served from public/; locally FastAPI serves it.
if not os.environ.get("VERCEL"):
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=ROOT / "public", html=True), name="public")
