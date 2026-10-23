"""HTTP middleware. The headers it adds are what the runtime sensors and the UI read."""
import time

from fastapi import FastAPI, Request

from app.db import start_request_stats


async def timing_headers(request: Request, call_next):
    stats = start_request_stats()
    started = time.perf_counter()
    response = await call_next(request)
    total_ms = (time.perf_counter() - started) * 1000
    response.headers["Server-Timing"] = f"db;dur={stats['ms']:.1f}, app;dur={total_ms:.1f}"
    response.headers["X-DB-Queries"] = str(stats["queries"])
    return response


def register_middleware(app: FastAPI):
    app.middleware("http")(timing_headers)
