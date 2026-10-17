from fastapi import APIRouter, Depends, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.exceptions import AppError
from app.models import PurchaseOrder
from app.models.enums import POSource, POStatus
from app.schemas.purchase_order import (ApproveRequest, GoodsReceiptOut, GoodsReceiptRequest,
                                        ManualPOCreate, ManualPOUpdate, POStatusUpdate,
                                        PurchaseOrderOut, RejectRequest)
from app.services import inventory_service, po_service

router = APIRouter()


def _get_po(db: Session, po_id: int) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id)
    if po is None:
        raise AppError(404, "Purchase Order tidak ditemukan")
    return po


@router.get("", response_model=list[PurchaseOrderOut])
def list_purchase_orders(status: POStatus | None = None, supplier_id: int | None = None,
                         planning_run_id: int | None = None, source: POSource | None = None,
                         db: Session = Depends(get_db)):
    stmt = select(PurchaseOrder).order_by(PurchaseOrder.id)
    if status is not None:
        stmt = stmt.where(PurchaseOrder.status == status)
    if supplier_id is not None:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    if planning_run_id is not None:
        stmt = stmt.where(PurchaseOrder.planning_run_id == planning_run_id)
    if source is not None:
        stmt = stmt.where(PurchaseOrder.source == source)
    return list(db.scalars(stmt))


@router.post("", response_model=PurchaseOrderOut, status_code=http_status.HTTP_201_CREATED)
def create_manual_po(body: ManualPOCreate, db: Session = Depends(get_db)):
    """Manual PO (tanpa planning run): DRAFT, source=MANUAL. `warnings` bila supplier belum terhubung ke material."""
    return po_service.create_manual(db, body.model_dump())


@router.get("/{po_id}", response_model=PurchaseOrderOut)
def get_purchase_order(po_id: int, db: Session = Depends(get_db)):
    return _get_po(db, po_id)


@router.patch("/{po_id}", response_model=PurchaseOrderOut)
def update_manual_po(po_id: int, body: ManualPOUpdate, db: Session = Depends(get_db)):
    """Edit Manual PO selama DRAFT / REJECTED (`items` = replace-all)."""
    return po_service.update_manual(db, _get_po(db, po_id), body.model_dump(exclude_unset=True))


@router.post("/{po_id}/submit", response_model=PurchaseOrderOut)
def submit_po(po_id: int, db: Session = Depends(get_db)):
    return po_service.submit(db, _get_po(db, po_id))


@router.post("/{po_id}/approve", response_model=PurchaseOrderOut)
def approve_po(po_id: int, body: ApproveRequest, db: Session = Depends(get_db)):
    return po_service.approve(db, _get_po(db, po_id), body.approved_by)


@router.post("/{po_id}/reject", response_model=PurchaseOrderOut)
def reject_po(po_id: int, body: RejectRequest, db: Session = Depends(get_db)):
    return po_service.reject(db, _get_po(db, po_id), body.rejected_by, body.reason)


@router.patch("/{po_id}/status", response_model=PurchaseOrderOut)
def update_po_status(po_id: int, body: POStatusUpdate, db: Session = Depends(get_db)):
    return po_service.change_status(db, _get_po(db, po_id), POStatus(body.status))


# ------------------- Phase 5: Goods Receipt (loop penutup) -------------------
@router.post("/{po_id}/receipts", response_model=GoodsReceiptOut)
def receive_goods(po_id: int, body: GoodsReceiptRequest, db: Session = Depends(get_db)):
    po = _get_po(db, po_id)
    changes = inventory_service.receive_goods(
        db, po, [(i.po_item_id, i.qty_received) for i in body.items])
    return {"po_id": po.id, "po_number": po.po_number, "po_status": po.status, "changes": changes}
