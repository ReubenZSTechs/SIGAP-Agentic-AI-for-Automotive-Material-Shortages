"""Records every LLM agent call in `agent_runs` so the Agent Hub (Streamlit) can show what each agent
received and returned.

A trace is one unit of work (a chat turn, a supplier message, a dispatch round …). Every agent call
inside it shares the trace id, so a whole flow (rewrite -> route -> parse -> clarify) can be followed
step by step. The current trace lives in a ContextVar, which `ThreadPoolExecutor` calls made with
`copy_context()` inherit. Recording never raises: tracking must not break a chat.
"""
import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

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


def purge_old(days: int | None = None) -> int:
    """Deletes runs older than `days` (default AGENT_TRACE_RETENTION_DAYS). Returns the number deleted."""
    from sqlalchemy import delete

    from app.database import SessionLocal
    from app.models import AgentRun
    days = settings.AGENT_TRACE_RETENTION_DAYS if days is None else days
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    with SessionLocal() as db:
        n = db.execute(delete(AgentRun).where(AgentRun.created_at < cutoff)).rowcount
        db.commit()
    return n or 0
