"""Riwayat setiap eksekusi tool Postgres (`tool_runs`) beserta SQL-nya, untuk Agent Hub (Streamlit)."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.orm import Session, undefer

from app.api.deps import get_db
from app.core.exceptions import AppError
from app.models import ToolRun

router = APIRouter()

LIGHT = ("id", "created_at", "tool", "kind", "workflow", "trace_id", "ref", "status", "error", "latency_ms",
         "row_count", "args")


def _light(r: ToolRun) -> dict:
    return {f: getattr(r, f) for f in LIGHT}


@router.get("")
def list_tool_runs(tool: list[str] | None = Query(None), kind: list[str] | None = Query(None),
                   workflow: list[str] | None = Query(None), status: list[str] | None = Query(None),
                   trace_id: str | None = None, q: str | None = None,
                   since: datetime | None = None, until: datetime | None = None,
                   limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                   db: Session = Depends(get_db)):
    """Eksekusi terbaru dulu (satu trace: urut waktu). Tanpa SQL/hasil; lihat `GET /{id}`."""
    stmt = select(ToolRun)
    if tool:
        stmt = stmt.where(ToolRun.tool.in_(tool))
    if kind:
        stmt = stmt.where(ToolRun.kind.in_(kind))
    if workflow:
        stmt = stmt.where(ToolRun.workflow.in_(workflow))
    if status:
        stmt = stmt.where(ToolRun.status.in_(status))
    if trace_id:
        stmt = stmt.where(ToolRun.trace_id == trace_id)
    if since:
        stmt = stmt.where(ToolRun.created_at >= since.replace(tzinfo=None))
    if until:
        stmt = stmt.where(ToolRun.created_at <= until.replace(tzinfo=None))
    if q:
        stmt = stmt.where(or_(cast(ToolRun.args, Text).ilike(f"%{q}%"), cast(ToolRun.statements, Text).ilike(f"%{q}%"),
                              ToolRun.error.ilike(f"%{q}%")))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    order = ToolRun.id.asc() if trace_id else ToolRun.id.desc()
    rows = db.scalars(stmt.order_by(order).limit(limit).offset(offset))
    return jsonable_encoder({"total": total, "items": [_light(r) for r in rows]})


@router.get("/facets")
def tool_facets(db: Session = Depends(get_db)):
    """Isi filter: tool, jenis, workflow, dan status beserta jumlahnya."""
    def counts(col):
        return [{"value": v, "count": n} for v, n in db.execute(
            select(col, func.count()).group_by(col).order_by(func.count().desc()))]
    return {"tools": counts(ToolRun.tool), "kinds": counts(ToolRun.kind), "workflows": counts(ToolRun.workflow),
            "statuses": counts(ToolRun.status)}


@router.get("/{run_id}")
def get_tool_run(run_id: int, db: Session = Depends(get_db)):
    r = db.scalar(select(ToolRun).options(undefer(ToolRun.result_preview), undefer(ToolRun.statements))
                  .where(ToolRun.id == run_id))
    if r is None:
        raise AppError(404, "Eksekusi tool tidak ditemukan")
    return jsonable_encoder({**_light(r), "result_preview": r.result_preview, "statements": r.statements})
