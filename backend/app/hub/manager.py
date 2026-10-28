"""Chat Manajer: cermin chat Telegram manajer (pesan agent -> manajer dan balasan manajer) di Hub.

Tombol dan balasan dari Hub melewati jalur yang sama dengan Telegram (`manager_graph`). Setiap
keputusan menghapus tombol yang sudah tidak berlaku di Telegram (`close_manager_buttons`), dan status
tombol di Hub diturunkan dari status permintaan revisi, jadi kedua sisi selalu sama.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import AppError
from app.database import SessionLocal
from app.hub import common as C
from app.hub.approvals import CHOICE_LABEL, CR_PENDING, choose_change_request
from app.models import POChangeRequest, SupplierMessage
from app.models.enums import ChangeRequestStatus, MessageDirection
from app.supplier_chat.service import button_cr_id
from configs.workflows.manager_graph import confirm_pending

MD, CRS = MessageDirection, ChangeRequestStatus


def _status(m: SupplierMessage) -> str:
    if m.error:
        return "FAILED"
    return "SENT" if m.telegram_message_id is not None else "SANDBOX"


def button_state(data: str, cr: POChangeRequest | None) -> str:
    """active = masih bisa dipilih · chosen = pilihan yang dijalankan · closed = tidak berlaku lagi."""
    parts = str(data).split(":")
    if cr is None:
        return "closed"
    kind, choice = parts[0], (parts[2] if len(parts) > 2 else None)
    if kind == "cr":
        return "active" if cr.status in CR_PENDING else ("chosen" if cr.manager_choice == choice else "closed")
    if kind == "crc":
        if cr.status == CRS.AWAITING_MANAGER_CONFIRM and cr.pending_choice == choice:
            return "active"
        return "chosen" if cr.manager_choice == choice else "closed"
    return "active" if cr.status == CRS.AWAITING_MANAGER_CONFIRM else "closed"     # crx


def _button_text(data: str) -> str:
    """`[tombol] cr:3:approve_change` dari Telegram -> teks yang terbaca manusia."""
    parts = data.split(":")
    if parts[0] == "crx":
        return f"Tidak, batalkan (revisi #{parts[1]})"
    if len(parts) == 3:
        return f"{'Ya, ' if parts[0] == 'crc' else ''}{CHOICE_LABEL.get(parts[2], parts[2])} (revisi #{parts[1]})"
    return data


def manager_thread(db: Session, limit: int = 200) -> dict:
    rows = list(db.scalars(select(SupplierMessage).where(SupplierMessage.direction.in_((MD.MANAGER_OUT, MD.MANAGER_IN)))
                           .order_by(SupplierMessage.id.desc()).limit(limit)))[::-1]
    ids = {button_cr_id(b.get("data")) for m in rows for b in (m.buttons or [])}
    ids |= {button_cr_id((m.agent_output or {}).get("button")) for m in rows}
    ids.discard(None)
    crs = {cr.id: cr for cr in db.scalars(select(POChangeRequest).where(POChangeRequest.id.in_(ids)))} if ids else {}
    messages = []
    for m in rows:
        out = m.agent_output or {}
        view = {"id": m.id, "at": C.iso(m.created_at), "conversation_id": m.conversation_id}
        if m.direction == MD.MANAGER_OUT:
            buttons = [{"label": b["label"], "data": b["data"],
                        "state": button_state(b["data"], crs.get(button_cr_id(b["data"])))} for b in m.buttons or []]
            cr_ids = sorted({button_cr_id(b["data"]) for b in buttons} - {None})
            view.update({"from": "AGENT", "text": m.text, "buttons": buttons, "status": _status(m), "error": m.error,
                         "approval_ids": [f"cr-{i}" for i in cr_ids]})
        else:
            source = out.get("source") or ("hub" if (m.text or "").startswith("[Hub]") else "telegram")
            text = m.text
            if out.get("button"):
                text = _button_text(out["button"])
            elif text.startswith("[tombol] "):                     # pesan lama tanpa agent_output
                text = _button_text(text.removeprefix("[tombol] "))
            elif text.startswith("[Hub] "):
                text = text.removeprefix("[Hub] ")
            view.update({"from": "MANAGER", "text": text, "source": source, "author": out.get("author")})
        messages.append(view)
    pending = sum(1 for cr in db.scalars(select(POChangeRequest.id).where(POChangeRequest.status.in_(CR_PENDING))))
    return {"messages": messages, "pending": pending, "mode": settings.TELEGRAM_MODE,
            "manager_chat": settings.TELEGRAM_MANAGER_CHAT_ID is not None or settings.TELEGRAM_MODE == "sandbox"}


def press_button(svc, data: str, actor: str) -> dict:
    """Tombol yang ditekan di Chat Manajer = tombol Telegram yang sama, dengan actor dari Hub."""
    actor = C.require_actor(actor)
    cr_id, parts = button_cr_id(data), data.split(":")
    if cr_id is None:
        raise AppError(422, "Tombol tidak dikenal")
    if parts[0] == "crc" and len(parts) == 3 and not confirm_pending(cr_id, parts[2]):
        raise AppError(409, f"Konfirmasi ini sudah tidak berlaku untuk revisi #{cr_id}")
    if parts[0] in ("cr", "crc") and len(parts) == 3:
        return choose_change_request(svc, cr_id, parts[2], actor)
    with SessionLocal() as db:
        cr = db.get(POChangeRequest, cr_id)
        if cr is None or cr.status != CRS.AWAITING_MANAGER_CONFIRM:
            raise AppError(409, f"Tidak ada pilihan yang menunggu konfirmasi untuk revisi #{cr_id}")
        db.add(SupplierMessage(chat_id=svc.manager_chat_id, direction=MD.MANAGER_IN,
                               text=f"[Hub] {actor}: Tidak, batalkan (revisi #{cr_id})",
                               agent_output={"source": "hub", "author": actor, "button": data}))
        C.audit(db, actor, "cancel_choice", "change_request", cr_id)
        db.commit()
    svc.mirror_to_manager(f"💬 {actor} via Hub: No, cancel the choice for request #{cr_id}.")
    return svc.manager_graph.invoke({"kind": "button", "data": data, "actor": f"{actor} via Hub"})


def send_text(svc, text: str, actor: str) -> dict:
    """Balasan teks bebas manajer dari Hub: dicerminkan ke Telegram, lalu ditafsirkan `manager_decision_agent`."""
    actor = C.require_actor(actor)
    if not svc.agents:
        raise AppError(503, "Agent belum dikonfigurasi: isi AICORE_* di backend/.env untuk menafsirkan balasan manajer.")
    return svc.handle_manager_text(text.strip(), author=actor)
