"""Executes confirmed PO changes through `po_service` (create + issue, update draft, delete, cancel)."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import POSupplierConfirmation, PurchaseOrder
from app.models.enums import POStatus
from app.services import po_service
from configs.tools.po_common import SCS, _unchanged, po_snapshot


# ------------------------------------ write actions ------------------------------------
def confirmation(db: Session, po_id: int) -> POSupplierConfirmation:
    conf = db.scalar(select(POSupplierConfirmation).where(POSupplierConfirmation.po_id == po_id))
    if conf is None:
        conf = POSupplierConfirmation(po_id=po_id, status=SCS.PENDING)
        db.add(conf)
        db.flush()
    return conf


def _get_po(db: Session, po_id: int | None) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id) if po_id else None
    if po is None:
        raise AppError(404, "Purchase Order tidak ditemukan (mungkin sudah dihapus)")
    return po


def _check_snapshot(po: PurchaseOrder, snap: dict) -> None:
    if not _unchanged(po, snap):
        raise AppError(409, f"PO {po.po_number} berubah sejak usulan dibuat; ulangi permintaan")


def create_and_issue_po(db: Session, group: dict, actor: str, notes: str | None = None) -> PurchaseOrder:
    """Manual PO -> submit -> approve (by `actor`) -> ISSUED, via the regular status machine."""
    data = {"supplier_id": group["supplier_id"], "po_date": date.today(), "notes": notes,
            "items": [{"material_id": i["material_id"], "qty_ordered": i["qty_ordered"], "unit_price": i["unit_price"],
                       "needed_by_date": date.fromisoformat(i["needed_by_date"]) if i.get("needed_by_date") else None}
                      for i in group["items"]]}
    po = po_service.create_manual(db, data)
    po_service.submit(db, po)
    po_service.approve(db, po, actor)
    po_service.change_status(db, po, POStatus.ISSUED)
    confirmation(db, po.id).status = SCS.PENDING
    db.flush()
    return po


def update_draft_po(db: Session, proposal: dict) -> PurchaseOrder:
    po = _get_po(db, proposal["po"]["id"])
    _check_snapshot(po, proposal["po"])
    data = {"items": [{"material_id": i["material_id"], "qty_ordered": i["qty_ordered"], "unit_price": i["unit_price"],
                       "needed_by_date": date.fromisoformat(i["needed_by_date"]) if i.get("needed_by_date") else None}
                      for i in proposal["items_after"]]}
    if proposal.get("notes"):
        data["notes"] = proposal["notes"][:500]
    return po_service.update_manual(db, po, data)


def delete_po(db: Session, po_id: int, snapshot: dict | None = None) -> dict:
    """Hard delete with stock revert (see `po_service.delete_po`); returns the PO snapshot."""
    po = _get_po(db, po_id)
    if snapshot is not None:
        _check_snapshot(po, snapshot)
    snap = po_snapshot(po)
    po_service.delete_po(db, po)
    return snap


def cancel_po(db: Session, po_id: int, reason: str, snapshot: dict | None = None) -> dict:
    """Cancels an issued PO but keeps it (status CANCELLED, "Dibatalkan"); returns the PO snapshot."""
    po = _get_po(db, po_id)
    if snapshot is not None:
        _check_snapshot(po, snapshot)
    snap = po_snapshot(po)
    po_service.cancel_issued(db, po, reason)
    return snap
