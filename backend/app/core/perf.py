"""Per-request database round trips, visible in the browser and in the logs.

Every response gets `Server-Timing: db;desc="N queries";dur=<ms in SQL>, app;dur=<total ms>` (DevTools ->
Network -> Timing). Requests above `SLOW_QUERIES` statements or `SLOW_MS` are logged as warnings. On SAP BTP each
statement is a round trip to the database (~140-200 ms), so the query count is the number to watch.
"""
import contextvars
import logging
import time

from sqlalchemy import event
from sqlalchemy.engine import Engine

log = logging.getLogger("app.perf")
SLOW_QUERIES = 20
SLOW_MS = 1000

# One mutable dict per request; sync endpoints run in a thread pool with a copied context, so they share it.
_stats: contextvars.ContextVar[dict | None] = contextvars.ContextVar("db_stats", default=None)


@event.listens_for(Engine, "before_cursor_execute")
def _before(conn, cursor, statement, params, context, executemany):
    conn.info.setdefault("_perf_start", []).append(time.perf_counter())


@event.listens_for(Engine, "after_cursor_execute")
def _after(conn, cursor, statement, params, context, executemany):
    started = conn.info.get("_perf_start")
    stats = _stats.get()
    if not started:
        return
    took = time.perf_counter() - started.pop()
    if stats is not None:
        stats["n"] += 1
        stats["s"] += took


async def server_timing(request, call_next):
    """HTTP middleware: counts statements and SQL time of one request (see module docstring)."""
    stats = {"n": 0, "s": 0.0}
    token = _stats.set(stats)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        _stats.reset(token)
    total_ms = (time.perf_counter() - started) * 1000
    response.headers["Server-Timing"] = (f'db;desc="{stats["n"]} queries";dur={stats["s"] * 1000:.0f}, '
                                         f"app;dur={total_ms:.0f}")
    response.headers["Timing-Allow-Origin"] = "*"           # frontend di origin lain juga boleh membacanya
    if stats["n"] > SLOW_QUERIES or total_ms > SLOW_MS:
        log.warning("slow request %s %s: %d queries, %.0f ms in SQL, %.0f ms total", request.method,
                    request.url.path, stats["n"], stats["s"] * 1000, total_ms)
    return response
