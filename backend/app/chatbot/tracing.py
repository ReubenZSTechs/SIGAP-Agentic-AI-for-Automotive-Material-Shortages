"""Records every LLM agent call in `agent_runs` and every Postgres tool execution in `tool_runs`, so the
Agent Hub (Streamlit) can show what each agent received and returned, and which SQL each tool ran.

A trace is one unit of work (a chat turn, a supplier message, a dispatch round …). Every agent call
inside it shares the trace id, so a whole flow (rewrite -> route -> parse -> clarify) can be followed
step by step. The current trace lives in a ContextVar, which `ThreadPoolExecutor` calls made with
`copy_context()` inherit. Recording never raises: tracking must not break a chat.
"""
import json
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.config import settings

log = logging.getLogger(__name__)

_current: ContextVar[dict | None] = ContextVar("agent_trace", default=None)


def new_trace(workflow: str, **ref) -> dict:
    """A trace for `workflow`; inside an active trace the id is kept and the refs are merged."""
    outer = _current.get()
    refs = {**((outer or {}).get("ref") or {}), **{k: v for k, v in ref.items() if v is not None}}
    return {"trace_id": outer["trace_id"] if outer else uuid.uuid4().hex, "workflow": workflow, "ref": refs}


@contextmanager
def activate(trace: dict):
    """Makes `trace` current for the block (use around each step of a generator, never across a yield)."""
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)


@contextmanager
def trace_scope(workflow: str, **ref):
    with activate(new_trace(workflow, **ref)) as trace:
        yield trace


def record_run(*, agent: str, model: str | None, system_prompt: str, input: str, output: dict | None,
               attempts: list[dict], status: str, error: str | None, latency_ms: int,
               input_tokens: int | None, output_tokens: int | None) -> None:
    if not settings.AGENT_TRACE_ENABLED:
        return
    trace = _current.get() or {"trace_id": uuid.uuid4().hex, "workflow": "other", "ref": {}}
    try:
        from app.database import SessionLocal
        from app.models import AgentRun
        with SessionLocal() as db:
            db.add(AgentRun(agent=agent, model=model, workflow=trace["workflow"], trace_id=trace["trace_id"],
                            ref=trace["ref"] or None, status=status, error=(error or None) and error[:500],
                            latency_ms=latency_ms, input_tokens=input_tokens, output_tokens=output_tokens,
                            output=output, input=input, system_prompt=system_prompt, attempts=attempts))
            db.commit()
    except Exception:  # noqa: BLE001  (pencatatan gagal tidak boleh menggagalkan agent)
        log.exception("recording agent run for %s failed", agent)


# ------------------------------------------------------------------ Postgres tool runs
MAX_STATEMENTS = 50          # SQL yang disimpan per tool run
MAX_PREVIEW_ROWS = 20        # baris hasil yang disimpan
MAX_TEXT = 4000              # panjang maksimum satu SQL / parameter

_tool_run: ContextVar["ToolRecorder | None"] = ContextVar("tool_run", default=None)


class ToolRecorder:
    """Collects what one tool execution did. Callers report the outcome with `done()` or `fail()`."""

    def __init__(self, tool: str, kind: str, args: dict | None):
        self.tool, self.kind, self.args = tool, kind, args
        self.statements: list[dict] = []
        self.row_count: int | None = None
        self.result = None
        self.error: str | None = None

    def done(self, rows=None) -> None:
        """Successful run; `rows` (list or dict) is stored as a short preview."""
        if isinstance(rows, list):
            self.row_count = len(rows)
            self.result = rows[:MAX_PREVIEW_ROWS]
        elif rows is not None:
            self.result = rows

    def fail(self, error: str) -> None:
        self.error = error

    def add_statement(self, sql: str, params=None, ms: float = 0.0) -> None:
        """Adds one executed SQL statement (also used for raw DB-API cursors that bypass SQLAlchemy events)."""
        if len(self.statements) < MAX_STATEMENTS:
            self.statements.append({"sql": str(sql)[:MAX_TEXT], "params": _short(params), "ms": round(ms, 2)})


def _short(params):
    if params in (None, (), [], {}):
        return None
    return repr(params)[:MAX_TEXT]


def _json_safe(value):
    """Dates, Decimals and enums -> strings, so the value fits in a JSON column."""
    return json.loads(json.dumps(value, default=str))


@event.listens_for(Engine, "before_cursor_execute")
def _before_sql(conn, cursor, statement, parameters, context, executemany):
    if _tool_run.get() is not None:
        conn.info.setdefault("tool_sql_started", []).append(time.perf_counter())


@event.listens_for(Engine, "after_cursor_execute")
def _after_sql(conn, cursor, statement, parameters, context, executemany):
    recorder = _tool_run.get()
    started = conn.info.get("tool_sql_started")
    if recorder is None or not started:
        return
    recorder.add_statement(statement, parameters, (time.perf_counter() - started.pop()) * 1000)


def current_tool() -> ToolRecorder | None:
    """The tool run in progress (None outside `record_tool`)."""
    return _tool_run.get()


@contextmanager
def record_tool(tool: str, kind: str, args: dict | None = None):
    """Records one Postgres tool execution in `tool_runs`, with every SQL statement it ran.

        with record_tool("get_stock_summary", "read", args) as run:
            rows = ...
            run.done(rows)

    An exception inside the block is recorded as an error and re-raised. Recording itself never raises.
    """
    recorder = ToolRecorder(tool, kind, args)
    token = _tool_run.set(recorder)
    started = time.perf_counter()
    try:
        yield recorder
    except BaseException as e:
        recorder.fail(f"{type(e).__name__}: {getattr(e, 'detail', None) or e}")
        raise
    finally:
        _tool_run.reset(token)
        _save_tool_run(recorder, int((time.perf_counter() - started) * 1000))


def _save_tool_run(recorder: ToolRecorder, latency_ms: int) -> None:
    if not settings.AGENT_TRACE_ENABLED:
        return
    trace = _current.get() or {"trace_id": uuid.uuid4().hex, "workflow": "other", "ref": {}}
    try:
        from app.database import SessionLocal
        from app.models import ToolRun
        with SessionLocal() as db:
            db.add(ToolRun(tool=recorder.tool, kind=recorder.kind, workflow=trace["workflow"],
                           trace_id=trace["trace_id"], ref=trace["ref"] or None,
                           status="error" if recorder.error else "ok",
                           error=(recorder.error or None) and recorder.error[:500], latency_ms=latency_ms,
                           row_count=recorder.row_count, args=_json_safe(recorder.args),
                           result_preview=_json_safe(recorder.result), statements=recorder.statements))
            db.commit()
    except Exception:  # noqa: BLE001  (pencatatan gagal tidak boleh menggagalkan tool)
        log.exception("recording tool run for %s failed", recorder.tool)


def purge_old(days: int | None = None) -> int:
    """Deletes agent and tool runs older than `days` (default AGENT_TRACE_RETENTION_DAYS). Returns the number deleted."""
    from sqlalchemy import delete

    from app.database import SessionLocal
    from app.models import AgentRun, ToolRun
    days = settings.AGENT_TRACE_RETENTION_DAYS if days is None else days
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    with SessionLocal() as db:
        n = db.execute(delete(AgentRun).where(AgentRun.created_at < cutoff)).rowcount or 0
        n += db.execute(delete(ToolRun).where(ToolRun.created_at < cutoff)).rowcount or 0
        db.commit()
    return n
