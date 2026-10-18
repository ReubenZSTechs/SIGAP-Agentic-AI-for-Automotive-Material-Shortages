"""MPS -> BOM Explosion -> Net Requirement & Stock Allocation (Phase 2)."""
from collections import defaultdict
from datetime import date

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (Inventory, POItem, PlanningLine, PlanningRun,
                        PurchaseOrder, Schedule)
from app.models.enums import (PlanningRunStatus, POSource, POStatus, ScheduleStatus, StockStatus)
from app.services import bom_service

# Status PO yang dihitung sebagai on_order, per sumber. Manual DRAFT sengaja TIDAK dihitung (masih coretan);
# PENDING_APPROVAL dihitung (pembeli sudah berkomitmen) agar planning tidak memesan hal yang sama.
COUNTED = {
    POSource.PLANNING: (POStatus.DRAFT, POStatus.ISSUED, POStatus.PARTIALLY_RECEIVED),
    POSource.MANUAL: (POStatus.PENDING_APPROVAL, POStatus.APPROVED, POStatus.ISSUED,
                      POStatus.PARTIALLY_RECEIVED),
}


def mark_runs_stale(db: Session) -> None:
    """Tandai semua run DRAFT basi (allocated global & on_order dapat berubah). Tidak commit."""
    db.execute(update(PlanningRun).where(PlanningRun.status == PlanningRunStatus.DRAFT)
               .values(is_stale=True))


def classify(available: float, safety: float) -> StockStatus:
    """available <= 0 -> CRITICAL; 0 < available < safety -> WARNING; else SAFE."""
    if available <= 0:
        return StockStatus.CRITICAL
    if available < safety:
        return StockStatus.WARNING
    return StockStatus.SAFE


def _on_order_map(db: Session) -> dict[int, float]:
    """Sisa qty PO terbuka yang belum diterima, per material."""
    counted = or_(*[and_(PurchaseOrder.source == src, PurchaseOrder.status.in_(sts))
                    for src, sts in COUNTED.items()])
    rows = db.execute(
        select(POItem.material_id, POItem.qty_ordered - POItem.qty_received)
        .select_from(POItem)
        .join(PurchaseOrder, POItem.po_id == PurchaseOrder.id)
        .where(counted)
    )
    out: dict[int, float] = defaultdict(float)
    for mid, remaining in rows:
        out[mid] += remaining
    return out


def run_planning(db: Session, date_from: date, date_to: date) -> PlanningRun:
    schedules = db.scalars(
        select(Schedule).where(
            Schedule.status == ScheduleStatus.PLANNED,
            Schedule.production_date.between(date_from, date_to))
    ).all()
    if not schedules:
        raise AppError(400, "Tidak ada jadwal produksi PLANNED pada rentang tanggal tersebut")

    graph = bom_service._load_graph(db)
    per_unit: dict[int, dict[int, float]] = {}
    gross: dict[int, float] = defaultdict(float)
    needed_by: dict[int, date] = {}

    for s in schedules:
        if s.product_id not in per_unit:                       # eksplosi 1 unit, di-cache
            per_unit[s.product_id] = bom_service.explode(db, s.product_id, 1, graph)
        for mid, q in per_unit[s.product_id].items():
            gross[mid] += q * s.target_qty
            needed_by[mid] = min(needed_by.get(mid, s.production_date), s.production_date)

    invs = {i.material_id: i for i in db.scalars(
        select(Inventory).execution_options(populate_existing=True))}
    on_order = _on_order_map(db)
    run = PlanningRun(date_from=date_from, date_to=date_to)

    for mid, g in gross.items():
        g = round(g, 6)
        inv = invs.get(mid)
        if inv is None:
            inv = Inventory(material_id=mid, on_hand=0.0, allocated=0.0, safety_stock=0.0)
            db.add(inv)
            invs[mid] = inv
        available = round(inv.on_hand - inv.allocated, 6)      # Stok Tersedia
        incoming = round(on_order.get(mid, 0.0), 6)
        run.lines.append(PlanningLine(
            material_id=mid, gross_requirement=g,
            on_hand=inv.on_hand, allocated=inv.allocated, available=available,
            on_order=incoming, safety_stock=inv.safety_stock,
            shortfall=round(max(0.0, inv.safety_stock - (available + incoming)), 6),
            status=classify(available, inv.safety_stock),
            needed_by=needed_by[mid]))

    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def summarize(run: PlanningRun) -> dict:
    counts = {s: 0 for s in StockStatus}
    for l in run.lines:
        counts[l.status] += 1
    return {"n_critical": counts[StockStatus.CRITICAL],
            "n_warning": counts[StockStatus.WARNING],
            "n_safe": counts[StockStatus.SAFE]}


_SEVERITY = {StockStatus.CRITICAL: 0, StockStatus.WARNING: 1, StockStatus.SAFE: 2}


def sorted_lines(lines: list[PlanningLine]) -> list[PlanningLine]:
    """Urut: CRITICAL -> WARNING -> SAFE, lalu SKU."""
    return sorted(lines, key=lambda l: (_SEVERITY[l.status], l.material.sku))
