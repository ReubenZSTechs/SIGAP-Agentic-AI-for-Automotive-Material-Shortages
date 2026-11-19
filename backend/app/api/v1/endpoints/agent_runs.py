"""Riwayat setiap panggilan agent LLM (`agent_runs`), untuk Agent Hub (Streamlit) dan evaluasi."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.orm import Session, undefer

from app.api.deps import get_db
from app.core.exceptions import AppError
from app.models import AgentRun

router = APIRouter()

LIGHT = ("id", "created_at", "agent", "model", "workflow", "trace_id", "ref", "status", "error", "latency_ms",
         "input_tokens", "output_tokens", "output")


def _light(r: AgentRun) -> dict:
    return {**{f: getattr(r, f) for f in LIGHT}, "retries": max(0, len(r.attempts or []) - 1)}


@router.get("")
def list_runs(agent: list[str] | None = Query(None), workflow: list[str] | None = Query(None),
              status: list[str] | None = Query(None), trace_id: str | None = None, q: str | None = None,
              since: datetime | None = None, until: datetime | None = None,
              limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    """Panggilan terbaru dulu (satu trace: urut waktu). Tanpa prompt/percobaan; lihat `GET /{id}`."""
    stmt = select(AgentRun).options(undefer(AgentRun.attempts))
    if agent:
        stmt = stmt.where(AgentRun.agent.in_(agent))
    if workflow:
        stmt = stmt.where(AgentRun.workflow.in_(workflow))
    if status:
        stmt = stmt.where(AgentRun.status.in_(status))
    if trace_id:
        stmt = stmt.where(AgentRun.trace_id == trace_id)
    if since:
        stmt = stmt.where(AgentRun.created_at >= since.replace(tzinfo=None))
    if until:
        stmt = stmt.where(AgentRun.created_at <= until.replace(tzinfo=None))
    if q:
        stmt = stmt.where(or_(AgentRun.input.ilike(f"%{q}%"), cast(AgentRun.output, Text).ilike(f"%{q}%"),
                              AgentRun.error.ilike(f"%{q}%")))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    order = AgentRun.id.asc() if trace_id else AgentRun.id.desc()
    rows = db.scalars(stmt.order_by(order).limit(limit).offset(offset))
    return jsonable_encoder({"total": total, "items": [_light(r) for r in rows]})


@router.get("/facets")
def facets(db: Session = Depends(get_db)):
    """Isi filter: agent, workflow, dan status beserta jumlahnya."""
    def counts(col):
        return [{"value": v, "count": n} for v, n in db.execute(
            select(col, func.count()).group_by(col).order_by(func.count().desc()))]
    return {"agents": counts(AgentRun.agent), "workflows": counts(AgentRun.workflow), "statuses": counts(AgentRun.status)}


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    r = db.scalar(select(AgentRun).options(undefer(AgentRun.input), undefer(AgentRun.system_prompt),
                                           undefer(AgentRun.attempts)).where(AgentRun.id == run_id))
    if r is None:
        raise AppError(404, "Panggilan agent tidak ditemukan")
    return jsonable_encoder({**_light(r), "input": r.input, "system_prompt": r.system_prompt, "attempts": r.attempts})
