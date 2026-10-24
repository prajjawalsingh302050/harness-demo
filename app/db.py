"""SQLite access with per-request query counting and slow-query logging.

The counters feed the Server-Timing and X-DB-Queries response headers,
which the runtime sensors read. All SQL must go through query().
"""
import contextvars
import logging
import sqlite3
import time
from pathlib import Path

# The SQLite file built by scripts/build_db.py.
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "shop.db"
# Queries at or above this many milliseconds are logged as slow.
SLOW_QUERY_MS = 5

log = logging.getLogger("app.db")
# One counter per request. A ContextVar keeps concurrent requests from mixing their counts.
_stats = contextvars.ContextVar("db_stats", default=None)


def start_request_stats():
    """Start a fresh query counter for the current request and return it (called by the middleware)."""
    stats = {"queries": 0, "ms": 0.0}
    _stats.set(stats)
    return stats


def connect():
    """Open the database read-only and immutable, with rows readable by column name."""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro&immutable=1", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def query(con, sql, params=()):
    """Run one SQL statement and return its rows.

    Every query is counted and timed for the current request, and logged as a slow query
    when it takes SLOW_QUERY_MS or more. Always pass values through `params` (? placeholders).
    """
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
