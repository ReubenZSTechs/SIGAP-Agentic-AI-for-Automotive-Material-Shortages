"""Supplier Telegram agent API (backend/ops level; the frontend uses the Hub API `/hub`, which builds on this)."""
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.chatbot.service import ChatUnavailable
from app.config import settings
from app.core.exceptions import AppError
from app.database import SessionLocal
from app.models import (POChangeRequest, POSupplierConfirmation, PurchaseOrder, Supplier, SupplierConversation,
                        SupplierMessage, SupplierTelegramLink)
from app.models.enums import ConversationStatus, MessageDirection
from app.supplier_chat.service import (SupplierChatService, deep_link, ensure_link, get_supplier_chat_service,
                                       manager_chat_id)
from app.supplier_chat.transport import sandbox_chat_id
from configs.tools import po_actions as A

router = APIRouter()


def service() -> SupplierChatService:
    try:
        return get_supplier_chat_service()
    except ChatUnavailable as e:
        raise AppError(503, str(e)) from e


def _sandbox_only() -> None:
    if settings.TELEGRAM_MODE != "sandbox":
        raise AppError(409, "Endpoint sandbox hanya aktif bila TELEGRAM_MODE=sandbox")


def _out(obj, *fields) -> dict:
    return jsonable_encoder({f: getattr(obj, f) for f in fields})


def _msg(m: SupplierMessage) -> dict:
    return _out(m, "id", "conversation_id", "supplier_id", "chat_id", "direction", "text", "buttons",
                "telegram_message_id", "agent_output", "error", "created_at")


def _conv(c: SupplierConversation) -> dict:
    return {**_out(c, "id", "po_id", "po_number", "supplier_id", "purpose", "status", "transport", "turn_count",
                   "outcome", "automation_action_id", "change_request_id", "created_at", "started_at",
                   "last_activity_at", "closed_at"), "supplier_name": c.supplier.name}


def _cr(cr: POChangeRequest) -> dict:
    return {**_out(cr, "id", "po_id", "po_number", "conversation_id", "supplier_id", "proposed_changes",
                   "invalid_changes", "supplier_message", "options", "status", "pending_choice", "manager_choice",
                   "decided_at", "result", "created_at", "po_snapshot"), "supplier_name": cr.supplier.name}


@router.get("/status")
def status():
    return {"mode": settings.TELEGRAM_MODE, "live": settings.telegram_live, "bot_username": settings.TELEGRAM_BOT_USERNAME,
            "manager_chat_id": manager_chat_id(), "ai_configured": settings.aicore_configured}


# ------------------------------------------- links -------------------------------------------
@router.get("/links")
def list_links(db: Session = Depends(get_db)):
    rows = []
    for sup in db.scalars(select(Supplier).order_by(Supplier.code)):
        link = ensure_link(db, sup.id)
        sandbox_only = link.chat_id is not None and link.chat_id == sandbox_chat_id(sup.id)
        live_chat = None if (sandbox_only and settings.TELEGRAM_MODE == "telegram") else link.chat_id
        rows.append({"supplier_id": sup.id, "supplier_code": sup.code, "supplier_name": sup.name,
                     "is_active": sup.is_active, "linked": live_chat is not None, "chat_id": live_chat,
                     "sandbox_link": sandbox_only,
                     "link_token": link.link_token, "deep_link": deep_link(link), "linked_at": link.linked_at})
    db.commit()
    return jsonable_encoder(rows)


@router.post("/links/{supplier_id}/sandbox")
def link_sandbox(supplier_id: int, db: Session = Depends(get_db), svc: SupplierChatService = Depends(service)):
    """Links a simulated chat for the supplier (sandbox) and starts its queued conversations."""
    _sandbox_only()
    if db.get(Supplier, supplier_id) is None:
        raise AppError(404, "Supplier tidak ditemukan")
    link = svc.link_sandbox(supplier_id)
    return {"supplier_id": supplier_id, "chat_id": link.chat_id}


# --------------------------------------- conversations ---------------------------------------
class StartConversation(BaseModel):
    po_id: int
    purpose: Literal["CONFIRM_ORDER", "CANCEL_ORDER"]


@router.get("/conversations")
def list_conversations(status: ConversationStatus | None = None, po_id: int | None = None,
                       db: Session = Depends(get_db)):
    stmt = select(SupplierConversation).order_by(SupplierConversation.id.desc()).limit(200)
    if status is not None:
        stmt = stmt.where(SupplierConversation.status == status)
    if po_id is not None:
        stmt = stmt.where(SupplierConversation.po_id == po_id)
    return [_conv(c) for c in db.scalars(stmt)]


@router.post("/conversations", status_code=201)
def start_conversation(body: StartConversation, svc: SupplierChatService = Depends(service)):
    """Queues a confirmation / cancellation conversation for an ISSUED PO, then dispatches."""
    with A.write_session() as db:
        po = db.get(PurchaseOrder, body.po_id)
        if po is None:
            raise AppError(404, "Purchase Order tidak ditemukan")
        cid = A.start_supplier_conversation(db, po, body.purpose).id
    svc.dispatch_queued()
    with SessionLocal() as db:
        return _conv(db.get(SupplierConversation, cid))


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conv = db.get(SupplierConversation, conversation_id)
    if conv is None:
        raise AppError(404, "Percakapan tidak ditemukan")
    po = db.get(PurchaseOrder, conv.po_id) if conv.po_id else None
    conf = db.scalar(select(POSupplierConfirmation).where(POSupplierConfirmation.po_id == conv.po_id)) if conv.po_id else None
    msgs = db.scalars(select(SupplierMessage).where(SupplierMessage.conversation_id == conv.id).order_by(SupplierMessage.id))
    crs = db.scalars(select(POChangeRequest).where(POChangeRequest.conversation_id == conv.id).order_by(POChangeRequest.id))
    return {**_conv(conv), "po_snapshot": conv.po_snapshot, "po": A.po_snapshot(po) if po else None,
            "confirmation": _out(conf, "status", "promised_delivery_date", "supplier_reference", "confirmed_at",
                                 "revision_round") if conf else None,
            "messages": [_msg(m) for m in msgs], "change_requests": [_cr(c) for c in crs]}


# ------------------------------------------- sandbox -------------------------------------------
class SandboxInbound(BaseModel):
    supplier_id: int
    text: str = Field(min_length=1, max_length=2000)


class SandboxManager(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    button: str | None = Field(default=None, min_length=3, max_length=64)

    @model_validator(mode="after")
    def _one_of(self):
        if (self.text is None) == (self.button is None):
            raise ValueError("Kirim tepat salah satu: text atau button")
        return self


def _new_messages(db: Session, after_id: int) -> list[dict]:
    return [_msg(m) for m in db.scalars(select(SupplierMessage).where(SupplierMessage.id > after_id)
                                        .order_by(SupplierMessage.id))]


def _last_message_id(db: Session) -> int:
    return db.scalar(select(SupplierMessage.id).order_by(SupplierMessage.id.desc()).limit(1)) or 0


@router.post("/sandbox/inbound")
def sandbox_inbound(body: SandboxInbound, db: Session = Depends(get_db), svc: SupplierChatService = Depends(service)):
    """Act as the supplier: the message goes through exactly the same path as a Telegram message."""
    _sandbox_only()
    link = db.scalar(select(SupplierTelegramLink).where(SupplierTelegramLink.supplier_id == body.supplier_id))
    if link is None or link.chat_id != sandbox_chat_id(body.supplier_id):
        raise AppError(409, "Supplier belum ditautkan ke chat sandbox (POST /links/{id}/sandbox)")
    before = _last_message_id(db)
    result = svc.handle_inbound(link.chat_id, body.text)
    db.expire_all()
    return {"result": jsonable_encoder(result), "messages": _new_messages(db, before)}


@router.post("/sandbox/manager")
def sandbox_manager(body: SandboxManager, db: Session = Depends(get_db), svc: SupplierChatService = Depends(service)):
    """Act as the manager: free text or a button's callback data (e.g. `cr:3:resource`)."""
    _sandbox_only()
    before = _last_message_id(db)
    result = (svc.handle_inbound(svc.manager_chat_id, body.text) if body.text
              else svc.handle_button(svc.manager_chat_id, body.button))
    db.expire_all()
    return {"result": jsonable_encoder({k: v for k, v in result.items() if k != "sends"}),
            "messages": _new_messages(db, before)}


@router.get("/manager-inbox")
def manager_inbox(limit: int = 100, db: Session = Depends(get_db)):
    msgs = db.scalars(select(SupplierMessage).where(SupplierMessage.direction.in_(
        (MessageDirection.MANAGER_OUT, MessageDirection.MANAGER_IN))).order_by(SupplierMessage.id.desc()).limit(limit))
    return {"messages": [_msg(m) for m in msgs][::-1]}


# --------------------------------------- change requests ---------------------------------------
@router.get("/change-requests")
def list_change_requests(db: Session = Depends(get_db)):
    return [_cr(c) for c in db.scalars(select(POChangeRequest).order_by(POChangeRequest.id.desc()).limit(100))]


@router.get("/change-requests/{cr_id}")
def get_change_request(cr_id: int, db: Session = Depends(get_db)):
    cr = db.get(POChangeRequest, cr_id)
    if cr is None:
        raise AppError(404, "Permintaan revisi tidak ditemukan")
    return _cr(cr)


@router.post("/dispatch")
def dispatch(svc: SupplierChatService = Depends(service)):
    """One worker iteration without Telegram polling (useful in sandbox without the worker)."""
    return {"started": svc.dispatch_queued(), "timeouts": svc.tick_timeouts()}
