"""Shared PO helpers: constants, the atomic write session, PO snapshots and exact text formatting.

Used by every PO module (resolution, execution, supplier conversations) and by the chat workflows.
"""
from contextlib import contextmanager
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.database import engine
from app.models import PurchaseOrder
from app.models.enums import (
    ChangeRequestStatus,
    ConversationStatus,
    PORevisionStatus,
    POStatus,
    SupplierConfirmationStatus,
)

CS, CRS, SCS, RS = ConversationStatus, ChangeRequestStatus, SupplierConfirmationStatus, PORevisionStatus
ACTIVE_CONVERSATION = (CS.AWAITING_SUPPLIER, CS.REVISION_REQUESTED)
OPEN_CONVERSATION = (CS.QUEUED, *ACTIVE_CONVERSATION)
EDITABLE = (POStatus.DRAFT, POStatus.REJECTED)
_FIELD = {"qty": "qty_ordered", "unit_price": "unit_price", "needed_by_date": "needed_by_date"}
MAX_OPTIONS = 6


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@contextmanager
def write_session():
    """One atomic unit of work around `po_service` calls.

    `po_service` commits after every step; with `create_savepoint` those commits only release
    savepoints, and the outer transaction commits once at the end (or rolls back entirely).
    """
    with engine.connect() as conn:
        trans = conn.begin()
        db = Session(bind=conn, autoflush=False, join_transaction_mode="create_savepoint")
        try:
            yield db
            db.commit()
            trans.commit()
        except BaseException:
            trans.rollback()
            raise
        finally:
            db.close()


# --------------------------------- snapshots & formatting ---------------------------------
def _iso(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def po_snapshot(po: PurchaseOrder) -> dict:
    """JSON copy of a PO (kept on conversations / change requests, survives a hard delete)."""
    return {
        "id": po.id, "po_number": po.po_number, "status": po.status.value, "source": po.source.value,
        "supplier_id": po.supplier_id, "supplier_code": po.supplier.code, "supplier_name": po.supplier.name,
        "payment_term_days": po.supplier.payment_term_days, "po_date": _iso(po.po_date),
        "total_amount": po.total_amount, "notes": po.notes,
        "items": [{"po_item_id": i.id, "material_id": i.material_id, "sku": i.sku, "name": i.name, "uom": i.uom,
                   "qty_ordered": i.qty_ordered, "qty_received": i.qty_received, "unit_price": i.unit_price,
                   "line_total": i.line_total, "needed_by_date": _iso(i.needed_by_date)} for i in po.items],
    }


def rupiah(n) -> str:
    return "Rp" + f"{round(n or 0):,}".replace(",", ".")


def fmt_qty(q) -> str:
    return str(int(q)) if float(q).is_integer() else f"{q:g}"


def po_summary_text(snap: dict) -> str:
    """Exact, deterministic PO details appended to every Telegram message (never LLM-written)."""
    lines = [f"{snap['po_number']} · {snap['supplier_name']}"]
    for n, it in enumerate(snap["items"], 1):
        need = f" · needed by {it['needed_by_date']}" if it.get("needed_by_date") else ""
        lines.append(f"{n}. {it['sku']} {it['name']} — {fmt_qty(it['qty_ordered'])} {it['uom']} × "
                     f"{rupiah(it['unit_price'])} = {rupiah(it['line_total'])}{need}")
    lines.append(f"Total: {rupiah(snap['total_amount'])} · Payment terms: Net {snap.get('payment_term_days', 0)}")
    return "\n".join(lines)


FIELD_LABEL = {"qty_ordered": "qty", "unit_price": "unit price", "needed_by_date": "needed-by date",
               "promised_delivery_date": "delivery date", "status": "status"}


def change_value(field: str, v) -> str:
    if field == "unit_price":
        return rupiah(v)
    if field == "qty_ordered":
        return fmt_qty(v)
    return str(v)


def describe_change(c: dict) -> str:
    """`{sku, name, field, old, new}` -> "RM-RUB-01 Ban Luar Karet: qty 50 → 40" (exact, never LLM-written)."""
    who = f"{c['sku']} {c['name']}".strip()
    return (f"{who}: {FIELD_LABEL.get(c['field'], c['field'])} {change_value(c['field'], c['old'] or '-')} → "
            f"{change_value(c['field'], c['new'])}")


def revision_diff_text(changes: list[dict], total_before: int, total_after: int) -> str:
    """What changed in an approved revision (sent to the supplier instead of the full PO again)."""
    lines = ["Approved changes:", *[f"- {describe_change(c)}" for c in changes]]
    if total_before != total_after:
        lines.append(f"Total: {rupiah(total_before)} → {rupiah(total_after)}")
    return "\n".join(lines)


def _unchanged(po: PurchaseOrder, snap: dict) -> bool:
    """True when status, total and every line still match the snapshot (guards stale decisions)."""
    if po.status.value != snap["status"] or po.total_amount != snap["total_amount"]:
        return False
    now_lines = {(i.id, i.qty_ordered, i.unit_price, i.qty_received) for i in po.items}
    then = {(i["po_item_id"], i["qty_ordered"], i["unit_price"], i["qty_received"]) for i in snap["items"]}
    return now_lines == then


def _has_receipts(po: PurchaseOrder) -> bool:
    return any(i.qty_received > 0 for i in po.items)
