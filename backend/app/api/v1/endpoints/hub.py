"""Agent Hub API (frontend "Hub Supplier"): persetujuan, percakapan, misi, dokumen, pengaturan.

Dibangun di atas agent Telegram supplier (`/supplier-chat`) tanpa mengubah endpoint lamanya.
"""
import threading

from fastapi import APIRouter, Depends, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.core.exceptions import AppError
from app.database import SessionLocal
from app.hub import approvals, common as C, documents, manager, missions, threads
from app.models import (HubAuditLog, HubDocument, HubMessageTemplate, HubMission, POChangeRequest, PurchaseOrder, Supplier,
                        SupplierConversation, SupplierMessage, SupplierTelegramLink)
from app.models.enums import MessageDirection
from app.models.hub import DocumentStatus, MissionStatus
from app.schemas.hub import (ActorIn, ApproveIn, ArchiveIn, ChooseIn, DecideIn, DocumentPatchIn, EscalateIn,
                             ManagerButtonIn, MessageIn, MissionIn, OutboxSendIn, RemindIn, SandboxAttachmentIn,
                             SandboxReplyIn, SupplierConversationIn, TemplateIn)
from app.supplier_chat.service import SupplierChatService, deep_link, ensure_link
from app.supplier_chat.transport import sandbox_chat_id
from configs.tools import po_actions as A

router = APIRouter()


def svc() -> SupplierChatService:
    return C.chat_service()


def _dispatch_later(service: SupplierChatService) -> None:
    """Kirim misi baru tanpa menunggu worker (mode sandbox / demo)."""
    threading.Thread(target=lambda: _safe_tick(service), daemon=True).start()


def _safe_tick(service) -> None:
    from app.hub.hooks import tick
    tick(service)


# --------------------------------------------- status ---------------------------------------------
@router.get("/status")
def status(db: Session = Depends(get_db)):
    st = C.hub_settings(db)
    unsent = db.query(SupplierMessage).filter(SupplierMessage.direction == MessageDirection.OUT,
                                              SupplierMessage.error.isnot(None),
                                              SupplierMessage.created_at >= A.now() - C.timedelta(hours=24)).count()
    thread_rows = threads.list_threads(db)
    out = {
        "paused": st.paused, "pending": approvals.pending_count(db), "ai_configured": settings.aicore_configured,
        "telegram": {"mode": settings.TELEGRAM_MODE, "live": settings.telegram_live, "bot": settings.TELEGRAM_BOT_USERNAME,
                     "connected": settings.TELEGRAM_MODE == "sandbox" or settings.telegram_live, "unsent": unsent},
        "counts": {
            "threads": sum(1 for t in thread_rows if t["unread"] or t["drafts"] or t["failed"]),
            "missions": db.query(HubMission).filter(HubMission.status == MissionStatus.ACTIVE).count(),
            "documents": db.query(HubDocument).filter(HubDocument.status == DocumentStatus.NEEDS_REVIEW).count(),
            "manager": db.query(POChangeRequest).filter(POChangeRequest.status.in_(approvals.CR_PENDING)).count(),
        },
    }
    db.commit()
    return out


@router.post("/agent/pause")
def pause(body: ActorIn, db: Session = Depends(get_db)):
    C.hub_settings(db).paused = True
    C.audit(db, body.approver, "pause", "hub", 1)
    db.commit()
    return {"paused": True}


@router.post("/agent/resume")
def resume(body: ActorIn, db: Session = Depends(get_db), service: SupplierChatService = Depends(svc)):
    C.hub_settings(db).paused = False
    C.audit(db, body.approver, "resume", "hub", 1)
    db.commit()
    _dispatch_later(service)
    return {"paused": False}


@router.post("/dispatch")
def dispatch(service: SupplierChatService = Depends(svc)):
    return missions.tick(service)


# ------------------------------------------- approvals -------------------------------------------
@router.get("/approvals")
def list_approvals(db: Session = Depends(get_db)):
    return jsonable_encoder(approvals.list_approvals(db))


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: str, db: Session = Depends(get_db)):
    return jsonable_encoder(approvals.get_approval(db, approval_id))


@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: str, body: ApproveIn):
    kind, num = approvals.parse_id(approval_id)
    if kind == "cr":
        raise AppError(422, "Revisi PO diputuskan dengan memilih opsi (POST /approvals/cr-{id}/choose)")
    return jsonable_encoder(approvals.approve_proposal(num, body.model_dump()))


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: str, body: DecideIn):
    kind, num = approvals.parse_id(approval_id)
    if kind == "cr":
        raise AppError(422, "Revisi PO diputuskan dengan memilih opsi (POST /approvals/cr-{id}/choose)")
    return jsonable_encoder(approvals.decide_proposal(num, "reject", body.model_dump()))


@router.post("/approvals/{approval_id}/request-revision")
def request_revision(approval_id: str, body: DecideIn):
    kind, num = approvals.parse_id(approval_id)
    if kind == "cr":
        raise AppError(422, "Revisi PO diputuskan dengan memilih opsi (POST /approvals/cr-{id}/choose)")
    return jsonable_encoder(approvals.decide_proposal(num, "revision", body.model_dump()))


@router.post("/approvals/{approval_id}/choose")
def choose(approval_id: str, body: ChooseIn, service: SupplierChatService = Depends(svc)):
    kind, num = approvals.parse_id(approval_id)
    if kind != "cr":
        raise AppError(422, "Pilihan opsi hanya untuk revisi PO")
    result = approvals.choose_change_request(service, num, body.choice, body.approver)
    return jsonable_encoder({k: v for k, v in result.items() if k != "sends"})


# ------------------------------------------- manager chat -------------------------------------------
@router.get("/manager/messages")
def manager_messages(db: Session = Depends(get_db)):
    return jsonable_encoder(manager.manager_thread(db))


@router.post("/manager/messages")
def manager_message(body: MessageIn, service: SupplierChatService = Depends(svc)):
    """Balasan teks manajer dari Hub (dicerminkan ke chat Telegram manajer)."""
    result = manager.send_text(service, body.text, body.approver)
    return jsonable_encoder({k: v for k, v in result.items() if k != "sends"})


@router.post("/manager/buttons")
def manager_button(body: ManagerButtonIn, service: SupplierChatService = Depends(svc)):
    """Tombol opsi dari Chat Manajer: sama dengan menekan tombol di Telegram."""
    result = manager.press_button(service, body.data, body.approver)
    if result.get("error"):
        raise AppError(409, result["error"])
    return jsonable_encoder({k: v for k, v in result.items() if k != "sends"})


# --------------------------------------------- threads ---------------------------------------------
@router.get("/threads")
def list_threads(db: Session = Depends(get_db)):
    return jsonable_encoder(threads.list_threads(db))


@router.get("/threads/{supplier_id}")
def get_thread(supplier_id: int, db: Session = Depends(get_db)):
    return jsonable_encoder(threads.get_thread(db, supplier_id))


@router.post("/threads/{supplier_id}/messages", status_code=201)
def send_message(supplier_id: int, body: MessageIn, db: Session = Depends(get_db),
                 service: SupplierChatService = Depends(svc)):
    return threads.send_manual(service, db, supplier_id, body.text.strip(), body.approver)


@router.post("/threads/{supplier_id}/takeover")
def takeover(supplier_id: int, body: ActorIn, db: Session = Depends(get_db)):
    threads.takeover(db, supplier_id, body.approver)
    return {"mode": "HUMAN"}


@router.post("/threads/{supplier_id}/release")
def release(supplier_id: int, body: ActorIn, db: Session = Depends(get_db)):
    threads.release(db, supplier_id, body.approver)
    return {"mode": "AGENT"}


@router.post("/threads/{supplier_id}/sandbox-reply")
def sandbox_reply(supplier_id: int, body: SandboxReplyIn, db: Session = Depends(get_db),
                  service: SupplierChatService = Depends(svc)):
    """Berperan sebagai supplier (mode sandbox): jalur yang sama persis dengan pesan Telegram."""
    if settings.TELEGRAM_MODE != "sandbox":
        raise AppError(409, "Simulasi hanya aktif bila TELEGRAM_MODE=sandbox")
    link = db.scalar(select(SupplierTelegramLink).where(SupplierTelegramLink.supplier_id == supplier_id))
    if link is None or link.chat_id != sandbox_chat_id(supplier_id):
        raise AppError(409, "Supplier belum ditautkan ke chat sandbox")
    if not service.agents:
        raise AppError(503, "Agent belum dikonfigurasi: isi AICORE_* di backend/.env untuk memproses balasan supplier.")
    result = service.handle_inbound(link.chat_id, body.text)
    return jsonable_encoder({k: v for k, v in (result or {}).items() if k != "sends"})


@router.post("/outbox/{outbox_id}/send")
def send_outbox(outbox_id: int, body: OutboxSendIn, db: Session = Depends(get_db),
                service: SupplierChatService = Depends(svc)):
    return threads.send_outbox(service, db, outbox_id, body.approver, body.text)


@router.post("/outbox/{outbox_id}/discard")
def discard_outbox(outbox_id: int, body: ActorIn, db: Session = Depends(get_db)):
    threads.discard_outbox(db, outbox_id, body.approver)
    return {"ok": True}


@router.post("/messages/{message_id}/retry")
def retry(message_id: int, body: ActorIn, db: Session = Depends(get_db), service: SupplierChatService = Depends(svc)):
    return threads.retry_message(service, db, message_id, body.approver)


# --------------------------------------------- missions ---------------------------------------------
@router.get("/mission-options")
def mission_options(db: Session = Depends(get_db)):
    return jsonable_encoder(missions.mission_options(db))


@router.get("/mission-options/po/{po_id}")
def mission_po_options(po_id: int, db: Session = Depends(get_db)):
    return jsonable_encoder(missions.po_options(db, po_id))


@router.get("/missions")
def list_missions(db: Session = Depends(get_db)):
    return jsonable_encoder(missions.list_missions(db))


@router.post("/missions", status_code=201)
def create_mission(body: MissionIn, db: Session = Depends(get_db), service: SupplierChatService = Depends(svc)):
    m = missions.create_mission(db, body.model_dump())
    missions.tick(service)                       # kirim langsung bila supplier siap (tanpa menunggu worker)
    db.expire_all()
    return jsonable_encoder(missions.get_mission(db, m.id))


@router.get("/missions/{mission_id}")
def get_mission(mission_id: int, db: Session = Depends(get_db)):
    return jsonable_encoder(missions.get_mission(db, mission_id))


@router.post("/missions/{mission_id}/remind")
def remind(mission_id: int, body: RemindIn, service: SupplierChatService = Depends(svc)):
    return missions.remind(service, mission_id, body.supplier_ids, body.approver)


@router.post("/missions/{mission_id}/escalate")
def escalate(mission_id: int, body: EscalateIn, service: SupplierChatService = Depends(svc)):
    missions.escalate(service, mission_id, body.supplier_id, body.approver)
    return {"ok": True}


@router.post("/missions/{mission_id}/close")
def close(mission_id: int, body: ActorIn, db: Session = Depends(get_db)):
    missions.close(mission_id, body.approver)
    return jsonable_encoder(missions.get_mission(db, mission_id))


@router.post("/missions/{mission_id}/cancel")
def cancel(mission_id: int, body: ActorIn, db: Session = Depends(get_db)):
    missions.cancel(mission_id, body.approver)
    return jsonable_encoder(missions.get_mission(db, mission_id))


@router.get("/po/{po_id}/context")
def po_context(po_id: int, db: Session = Depends(get_db)):
    return jsonable_encoder(missions.po_context(db, po_id))


@router.post("/po/{po_id}/supplier-conversation", status_code=201)
def start_supplier_conversation(po_id: int, body: SupplierConversationIn, service: SupplierChatService = Depends(svc)):
    """Kirim PO ISSUED ke supplier (konfirmasi) atau minta persetujuan pembatalan, dari halaman detail PO."""
    with A.write_session() as db:
        po = db.get(PurchaseOrder, po_id)
        if po is None:
            raise AppError(404, "Purchase Order tidak ditemukan")
        conv = A.start_supplier_conversation(db, po, body.purpose)
        C.audit(db, body.approver, "start_conversation", "po", po_id, purpose=body.purpose)
        cid = conv.id
    service.dispatch_queued()
    with SessionLocal() as db:
        conv = db.get(SupplierConversation, cid)
        return {"id": conv.id, "status": conv.status.value, "purpose": conv.purpose.value}


# --------------------------------------------- documents ---------------------------------------------
@router.get("/documents")
def list_documents(db: Session = Depends(get_db)):
    return jsonable_encoder(documents.list_documents(db))


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db)):
    return jsonable_encoder(documents.get_document(db, doc_id))


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: int, db: Session = Depends(get_db)):
    content, mime, name = documents.file_content(db, doc_id)
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "._- ")[:120] or "dokumen"
    return Response(content, media_type=mime, headers={"Content-Disposition": f'inline; filename="{safe}"'})


@router.patch("/documents/{doc_id}")
def patch_document(doc_id: int, body: DocumentPatchIn, db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    actor = data.pop("approver")
    return jsonable_encoder(documents.update_fields(db, doc_id, data, actor))


@router.post("/documents/{doc_id}/archive")
def archive_document(doc_id: int, body: ArchiveIn, db: Session = Depends(get_db)):
    return jsonable_encoder(documents.archive(db, doc_id, body.approver, body.confirm_mismatch))


@router.post("/documents/{doc_id}/request-again")
def request_again(doc_id: int, body: DecideIn, service: SupplierChatService = Depends(svc)):
    return jsonable_encoder(documents.request_again(service, doc_id, body.approver, body.reason))


@router.post("/sandbox/attachment", status_code=201)
def sandbox_attachment(body: SandboxAttachmentIn, service: SupplierChatService = Depends(svc)):
    return documents.sandbox_upload(service, body.model_dump())


# --------------------------------------------- settings ---------------------------------------------
@router.get("/policies")
def get_policies(db: Session = Depends(get_db)):
    p = C.policies(db)
    db.commit()
    return {**p, "po_agent": {k: v for k, v in C.load_registry().supplier_chat.items()
                              if k in ("reminder_after_hours", "escalate_after_hours", "change_request_ttl_hours",
                                       "max_turns", "max_revision_rounds")}}


@router.put("/policies")
def put_policies(body: dict, db: Session = Depends(get_db)):
    actor = C.require_actor(body.get("approver"))
    row = C.hub_settings(db)
    row.policies = C.validate_policies(body)
    C.audit(db, actor, "update_policies", "hub", 1)
    db.commit()
    return row.policies


def _tpl(t: HubMessageTemplate) -> dict:
    return {"id": t.id, "name": t.name, "scenario": t.scenario, "body": t.body, "updated_at": C.iso(t.updated_at)}


@router.get("/templates")
def list_templates(db: Session = Depends(get_db)):
    rows = C.ensure_templates(db)
    db.commit()
    return [_tpl(t) for t in rows]


@router.post("/templates", status_code=201)
def create_template(body: TemplateIn, db: Session = Depends(get_db)):
    t = HubMessageTemplate(**body.model_dump())
    db.add(t)
    db.commit()
    return _tpl(t)


@router.put("/templates/{template_id}")
def update_template(template_id: int, body: TemplateIn, db: Session = Depends(get_db)):
    t = db.get(HubMessageTemplate, template_id)
    if t is None:
        raise AppError(404, "Template tidak ditemukan")
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    db.commit()
    db.refresh(t)
    return _tpl(t)


def _supplier_row(db: Session, sup: Supplier) -> dict:
    """Tanpa menulis apa pun (tautan /start baru dibuat saat undangan dikirim)."""
    link = db.scalar(select(SupplierTelegramLink).where(SupplierTelegramLink.supplier_id == sup.id))
    view = threads.supplier_view(db, sup)
    has_msgs = db.query(SupplierMessage.id).filter(SupplierMessage.supplier_id == sup.id).first() is not None
    return {**view, "is_active": sup.is_active, "deep_link": deep_link(link) if link else None,
            "linked_at": C.iso(link.linked_at) if link else None, "thread_id": sup.id if has_msgs else None}


@router.get("/suppliers")
def list_suppliers(db: Session = Depends(get_db)):
    return [_supplier_row(db, s) for s in db.scalars(select(Supplier).order_by(Supplier.name))]


@router.get("/suppliers/{supplier_id}")
def get_supplier(supplier_id: int, db: Session = Depends(get_db)):
    sup = db.get(Supplier, supplier_id)
    if sup is None:
        raise AppError(404, "Supplier tidak ditemukan")
    return _supplier_row(db, sup)


@router.post("/suppliers/{supplier_id}/invite")
def invite(supplier_id: int, body: ActorIn, db: Session = Depends(get_db)):
    """Undangan Telegram: deep link t.me/<bot>?start=<token> (token dari `ensure_link` yang sudah ada)."""
    sup = db.get(Supplier, supplier_id)
    if sup is None:
        raise AppError(404, "Supplier tidak ditemukan")
    link = ensure_link(db, supplier_id)
    C.control(db, supplier_id).invited_at = A.now()
    C.audit(db, body.approver, "invite", "supplier", supplier_id)
    db.commit()
    return {"link": deep_link(link), "token": link.link_token, "mode": settings.TELEGRAM_MODE,
            "bot": settings.TELEGRAM_BOT_USERNAME, "sandbox": settings.TELEGRAM_MODE == "sandbox"}


@router.post("/suppliers/{supplier_id}/link-sandbox")
def link_sandbox(supplier_id: int, body: ActorIn, db: Session = Depends(get_db),
                 service: SupplierChatService = Depends(svc)):
    """Mode sandbox: tautkan chat simulasi (sama dengan Telegram Lab) lalu jalankan antrean."""
    if settings.TELEGRAM_MODE != "sandbox":
        raise AppError(409, "Hanya untuk TELEGRAM_MODE=sandbox")
    if db.get(Supplier, supplier_id) is None:
        raise AppError(404, "Supplier tidak ditemukan")
    link = ensure_link(db, supplier_id)
    link.chat_id, link.linked_at = sandbox_chat_id(supplier_id), A.now()
    C.audit(db, body.approver, "link_sandbox", "supplier", supplier_id)
    db.commit()
    service.dispatch_queued()
    missions.tick(service)
    return {"supplier_id": supplier_id, "chat_id": link.chat_id}


@router.get("/audit")
def audit_log(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.scalars(select(HubAuditLog).order_by(HubAuditLog.id.desc()).limit(min(limit, 500)))
    return [{"id": a.id, "at": C.iso(a.at), "actor": a.actor, "action": a.action, "ref_type": a.ref_type,
             "ref_id": a.ref_id, "detail": a.detail} for a in rows]
