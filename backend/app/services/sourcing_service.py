"""Smart Sourcing: cocokkan defisit dengan supplier di Master Material (Phase 3)."""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import PlanningLine, PlanningRun
from app.models.enums import PlanningRunStatus, SourcingStrategy


def recommend(db: Session, line: PlanningLine,
              strategy: SourcingStrategy = SourcingStrategy.CHEAPEST,
              respect_moq: bool = True, max_lead_days: int | None = None) -> list[dict]:
    links = [l for l in line.material.supplier_links if l.is_active and l.supplier.is_active]
    opts = []
    for l in links:
        qty = max(line.shortfall, l.moq)
        opts.append({
            "supplier_id": l.supplier_id, "supplier_name": l.supplier.name,
            "unit_price": l.unit_price, "lead_time_days": l.lead_time_days,
            "moq": l.moq, "suggested_qty": qty, "est_total": round(qty * l.unit_price),
            "meets_moq": line.shortfall >= l.moq,
            "will_be_late": bool(line.needed_by and
                                 date.today() + timedelta(days=l.lead_time_days) > line.needed_by),
            "is_preferred": l.is_preferred,
        })
    if max_lead_days is not None:
        opts = [o for o in opts if o["lead_time_days"] <= max_lead_days]
    if respect_moq and any(o["meets_moq"] for o in opts):
        opts = [o for o in opts if o["meets_moq"]]
    if not opts:
        return []

    min_price = min(o["unit_price"] for o in opts)
    min_lead = min(o["lead_time_days"] for o in opts)
    for o in opts:
        o["is_cheapest"] = o["unit_price"] == min_price
        o["is_fastest"] = o["lead_time_days"] == min_lead

    keys = {
        SourcingStrategy.CHEAPEST: lambda o: (o["unit_price"], o["lead_time_days"]),
        SourcingStrategy.FASTEST: lambda o: (o["lead_time_days"], o["unit_price"]),
        SourcingStrategy.BALANCED: lambda o: 0.5 * o["unit_price"] / max(min_price, 1)
                                             + 0.5 * o["lead_time_days"] / max(min_lead, 1),
    }
    opts.sort(key=keys[strategy])
    for rank, o in enumerate(opts, 1):
        o["rank"] = rank
    return opts


def _ensure_editable(line: PlanningLine) -> None:
    if line.run.status == PlanningRunStatus.PO_GENERATED:
        raise AppError(409, "Planning run sudah PO_GENERATED; pilihan supplier tidak dapat diubah")


def select_supplier(db: Session, line: PlanningLine, supplier_id: int,
                    order_qty: float | None = None) -> PlanningLine:
    _ensure_editable(line)
    if line.shortfall <= 0:
        raise AppError(400, "Material ini tidak memiliki defisit; tidak perlu dipesan")
    link = next((l for l in line.material.supplier_links
                 if l.supplier_id == supplier_id and l.is_active), None)
    if link is None:
        raise AppError(400, "Supplier tidak terdaftar untuk material ini")
    qty = order_qty if order_qty is not None else max(line.shortfall, link.moq)
    if qty < line.shortfall or qty < link.moq:
        raise AppError(400, "order_qty harus ≥ defisit dan ≥ MOQ supplier")
    line.selected_supplier_id = supplier_id
    line.order_qty = qty
    line.unit_price = link.unit_price           # snapshot harga
    line.lead_time_days = link.lead_time_days
    db.commit()
    db.refresh(line)
    return line


def clear_selection(db: Session, line: PlanningLine) -> None:
    _ensure_editable(line)
    line.selected_supplier_id = None
    line.order_qty = None
    line.unit_price = None
    line.lead_time_days = None
    db.commit()


def auto_select(db: Session, run: PlanningRun, strategy: SourcingStrategy) -> tuple[list[PlanningLine], list[str]]:
    """Pilih opsi rank-1 untuk baris defisit yang belum dipilih."""
    if run.status == PlanningRunStatus.PO_GENERATED:
        raise AppError(409, "Planning run sudah PO_GENERATED")
    selected, skipped = [], []
    for line in run.lines:
        if line.shortfall <= 0 or line.selected_supplier_id is not None:
            continue
        opts = recommend(db, line, strategy)
        if not opts:
            skipped.append(line.material.sku)
            continue
        selected.append(select_supplier(db, line, opts[0]["supplier_id"]))
    return selected, skipped
