"""SQLite access with per-request query counting and slow-query logging.

The counters feed the Server-Timing and X-DB-Queries response headers,
which the runtime sensors read.
"""
import contextvars
import logging
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "shop.db"
SLOW_QUERY_MS = 5

log = logging.getLogger("app.db")
_stats = contextvars.ContextVar("db_stats", default=None)


def start_request_stats():
    stats = {"queries": 0, "ms": 0.0}
    _stats.set(stats)
    return stats


def connect():
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro&immutable=1", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def query(con, sql, params=()):
    started = time.perf_counter()
    rows = con.execute(sql, params).fetchall()
    ms = (time.perf_counter() - started) * 1000

    stats = _stats.get()
    if stats is not None:
        stats["queries"] += 1
        stats["ms"] += ms
    if ms >= SLOW_QUERY_MS:
        log.warning("slow query %.1fms: %s", ms, " ".join(sql.split()))
    return rows
