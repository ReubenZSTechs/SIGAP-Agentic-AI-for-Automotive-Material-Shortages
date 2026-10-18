from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.exceptions import AppError
from app.models import PlanningLine, PlanningRun
from app.models.enums import SourcingStrategy, StockStatus
from app.schemas.planning import (AutoSelectRequest, AutoSelectResult, PlanningLineOut,
                                  PlanningRunCreate, PlanningRunDetail, PlanningRunSummary,
                                  SelectionUpdate, SourcingItem)
from app.schemas.purchase_order import PurchaseOrderOut
from app.services import planning_service, po_service, sourcing_service

router = APIRouter()


def _get_run(db: Session, run_id: int) -> PlanningRun:
    run = db.get(PlanningRun, run_id)
    if run is None:
        raise AppError(404, "Planning run tidak ditemukan")
    return run


def _get_line(db: Session, line_id: int) -> PlanningLine:
    line = db.get(PlanningLine, line_id)
    if line is None:
        raise AppError(404, "Planning line tidak ditemukan")
    return line


def _summary(run: PlanningRun) -> dict:
    return {"id": run.id, "date_from": run.date_from, "date_to": run.date_to,
            "status": run.status, "created_at": run.created_at, "is_stale": run.is_stale,
            **planning_service.summarize(run)}


# ------------------------- Phase 2: Stock Planning -------------------------
@router.post("/runs", response_model=PlanningRunDetail, status_code=status.HTTP_201_CREATED)
def create_run(body: PlanningRunCreate, db: Session = Depends(get_db)):
    run = planning_service.run_planning(db, body.date_from, body.date_to)
    return {**_summary(run), "lines": planning_service.sorted_lines(run.lines)}


@router.get("/runs", response_model=list[PlanningRunSummary])
def list_runs(db: Session = Depends(get_db)):
    runs = db.scalars(select(PlanningRun).order_by(PlanningRun.id.desc())).all()
    return [_summary(r) for r in runs]


@router.get("/runs/{run_id}", response_model=PlanningRunSummary)
def get_run(run_id: int, db: Session = Depends(get_db)):
    return _summary(_get_run(db, run_id))


@router.get("/runs/{run_id}/lines", response_model=list[PlanningLineOut])
def get_run_lines(run_id: int, status: StockStatus | None = None, db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    lines = [l for l in run.lines if status is None or l.status == status]
    return planning_service.sorted_lines(lines)


# ------------------- Phase 3: Smart Sourcing & Selection -------------------
@router.get("/runs/{run_id}/sourcing", response_model=list[SourcingItem])
def get_sourcing(run_id: int, strategy: SourcingStrategy = SourcingStrategy.CHEAPEST,
                 respect_moq: bool = True, max_lead_days: int | None = Query(None, ge=0),
                 db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    out = []
    for line in planning_service.sorted_lines([l for l in run.lines if l.shortfall > 0]):
        options = sourcing_service.recommend(db, line, strategy, respect_moq, max_lead_days)
        out.append({"line": line, "deficit": line.shortfall,
                    "no_supplier": len(line.material.supplier_links) == 0,
                    "options": options})
    return out


@router.post("/runs/{run_id}/sourcing/auto-select", response_model=AutoSelectResult)
def auto_select(run_id: int, body: AutoSelectRequest | None = None, db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    strategy = body.strategy if body else SourcingStrategy.CHEAPEST
    selected, skipped = sourcing_service.auto_select(db, run, strategy)
    return {"selected": len(selected), "skipped_no_supplier": skipped,
            "lines": planning_service.sorted_lines(run.lines)}


@router.put("/lines/{line_id}/selection", response_model=PlanningLineOut)
def select_supplier(line_id: int, body: SelectionUpdate, db: Session = Depends(get_db)):
    line = _get_line(db, line_id)
    return sourcing_service.select_supplier(db, line, body.supplier_id, body.order_qty)


@router.delete("/lines/{line_id}/selection", status_code=status.HTTP_204_NO_CONTENT)
def clear_selection(line_id: int, db: Session = Depends(get_db)):
    sourcing_service.clear_selection(db, _get_line(db, line_id))


# ---------------------- Phase 4: PO Multi-Vendor ----------------------
@router.post("/runs/{run_id}/purchase-orders", response_model=list[PurchaseOrderOut],
             status_code=status.HTTP_201_CREATED)
def generate_purchase_orders(run_id: int, db: Session = Depends(get_db)):
    return po_service.generate_pos(db, _get_run(db, run_id))
