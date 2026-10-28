import logging

from fastapi import APIRouter, Depends, Response, status as http_status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, undefer

from app.api.deps import get_db
from app.core.exceptions import AppError
from app.models import POItem, PORevision, PurchaseOrder
from app.models.enums import PORevisionStatus, POSource, POStatus
from app.schemas.purchase_order import (ApproveRequest, GoodsReceiptOut, GoodsReceiptRequest,
                                        ManualPOCreate, ManualPOUpdate, POStatusUpdate,
                                        PurchaseOrderOut, RejectRequest)
from app.services import inventory_service, po_service

router = APIRouter()
log = logging.getLogger(__name__)


def _get_po(db: Session, po_id: int) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id)
    if po is None:
        raise AppError(404, "Purchase Order tidak ditemukan")
    return po


@router.get("", response_model=list[PurchaseOrderOut])
def list_purchase_orders(status: POStatus | None = None, supplier_id: int | None = None,
                         planning_run_id: int | None = None, source: POSource | None = None,
                         db: Session = Depends(get_db)):
    # supplier + items + materials in 3 extra queries in total, not per PO (each round trip is ~140 ms on SAP BTP)
    stmt = select(PurchaseOrder).order_by(PurchaseOrder.id).options(
        selectinload(PurchaseOrder.supplier), selectinload(PurchaseOrder.items).selectinload(POItem.material))
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


def _send_to_supplier(po_id: int) -> None:
    """PO yang baru ISSUED dikirim ke supplier via Telegram (sama seperti PO dari kartu Dashboard)."""
    from app.supplier_chat.service import dispatch_in_background
    from configs.tools import po_actions as A
    try:
        with A.write_session() as db:
            conv = A.ensure_confirm_conversation(db, db.get(PurchaseOrder, po_id))
        if conv is not None:
            dispatch_in_background()
    except Exception:  # noqa: BLE001  (status PO sudah tersimpan; worker/Hub dapat mengirim ulang)
        log.exception("queueing supplier confirmation for PO %s failed", po_id)


@router.patch("/{po_id}/status", response_model=PurchaseOrderOut)
def update_po_status(po_id: int, body: POStatusUpdate, db: Session = Depends(get_db)):
    po = po_service.change_status(db, _get_po(db, po_id), POStatus(body.status))
    if po.status == POStatus.ISSUED:
        _send_to_supplier(po.id)
        db.refresh(po)
    return po


# ------------------- Versi PO yang dibahas dengan supplier -------------------
def _revision_out(r: PORevision) -> dict:
    from configs.tools import po_actions as A
    return {"id": r.id, "version": r.version, "status": r.status.value, "total_amount": r.snapshot["total_amount"],
            "items": r.snapshot["items"], "changes": [{**c, "text": A.describe_change(c)} for c in r.changes or []],
            "change_request_id": r.change_request_id, "created_by": r.created_by, "created_at": r.created_at,
            "finalized_at": r.finalized_at, "pdf_sent": r.pdf_message_id is not None}


@router.get("/{po_id}/revisions")
def list_revisions(po_id: int, db: Session = Depends(get_db)):
    """v1 = PO yang pertama dikirim ke supplier, v2+ = revisi yang disetujui; FINAL = dikonfirmasi supplier."""
    _get_po(db, po_id)
    rows = db.scalars(select(PORevision).where(PORevision.po_id == po_id).order_by(PORevision.version))
    return jsonable_encoder([_revision_out(r) for r in rows])


@router.get("/{po_id}/revisions/{revision_id}/pdf")
def revision_pdf(po_id: int, revision_id: int, db: Session = Depends(get_db)):
    """PDF yang dikirim ke supplier (versi FINAL), atau dibuat saat itu juga untuk versi lain."""
    from app.supplier_chat.po_pdf import pdf_file_name, render_po_pdf
    rev = db.scalar(select(PORevision).options(undefer(PORevision.pdf))
                    .where(PORevision.id == revision_id, PORevision.po_id == po_id))
    if rev is None:
        raise AppError(404, "Versi PO tidak ditemukan")
    content = rev.pdf or render_po_pdf(rev.snapshot, rev.version, final=rev.status == PORevisionStatus.FINAL,
                                       finalized_at=rev.finalized_at)
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{pdf_file_name(rev.po_number, rev.version)}"'})


# ------------------- Phase 5: Goods Receipt (loop penutup) -------------------
@router.post("/{po_id}/receipts", response_model=GoodsReceiptOut)
def receive_goods(po_id: int, body: GoodsReceiptRequest, db: Session = Depends(get_db)):
    po = _get_po(db, po_id)
    changes = inventory_service.receive_goods(
        db, po, [(i.po_item_id, i.qty_received) for i in body.items])
    return {"po_id": po.id, "po_number": po.po_number, "po_status": po.status, "changes": changes}
