"""Thread percakapan per supplier: gabungan `supplier_messages`, draf `hub_outbox`, dan kejadian audit Hub."""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (HubAuditLog, HubDocument, HubMission, HubMissionTarget, HubOutbox, HubProposal,
                        HubSupplierControl, POChangeRequest, PurchaseOrder, Supplier, SupplierConversation,
                        SupplierMessage, SupplierTelegramLink)
from app.models.enums import MessageDirection, POStatus
from app.models.hub import MissionStatus, OutboxStatus, TargetState, ThreadMode
from app.hub import common as C
from configs.tools import po_actions as A

MD = MessageDirection
OPEN_PO = (POStatus.ISSUED, POStatus.PARTIALLY_RECEIVED)
DECISION_LABEL = {"confirmed": "Konfirmasi", "declined": "Menolak", "change_requested": "Minta revisi",
                  "question": "Pertanyaan", "unclear": "Belum jelas", "answered": "Menjawab"}
FIELD_LABEL = {"qty": "qty", "unit_price": "harga", "needed_by_date": "tanggal"}
SYSTEM_ACTIONS = {"takeover": "{actor} mengambil alih percakapan. Agent dijeda untuk supplier ini.",
                  "release": "{actor} menyerahkan percakapan kembali ke Agent.",
                  "discard_draft": "{actor} membuang draf pesan.",
                  "escalate": "Eskalasi Misi #{mission} ditandai oleh {actor}."}


def _supplier(db: Session, supplier_id: int) -> Supplier:
    sup = db.get(Supplier, supplier_id)
    if sup is None:
        raise AppError(404, "Supplier tidak ditemukan")
    return sup


def supplier_view(db: Session, sup: Supplier) -> dict:
    link = db.scalar(select(SupplierTelegramLink).where(SupplierTelegramLink.supplier_id == sup.id))
    ctl = db.scalar(select(HubSupplierControl).where(HubSupplierControl.supplier_id == sup.id))
    state, sandbox = C.telegram_state(link, ctl)
    return {"id": sup.id, "code": sup.code, "name": sup.name, "contact": C.contact_name(sup), "contact_raw": sup.contact,
            "telegram": state, "sandbox": sandbox, "handle": None,
            "avg_response_min": avg_response_minutes(db, sup.id)}


def avg_response_minutes(db: Session, supplier_id: int) -> int | None:
    """Rata-rata jeda OUT -> IN berikutnya (60 pesan terakhir)."""
    rows = list(db.scalars(select(SupplierMessage).where(SupplierMessage.supplier_id == supplier_id,
                                                         SupplierMessage.direction.in_((MD.OUT, MD.IN)))
                           .order_by(SupplierMessage.id.desc()).limit(60)))[::-1]
    gaps, last_out = [], None
    for m in rows:
        if m.direction == MD.OUT:
            last_out = last_out or m.created_at
        elif last_out is not None:
            gaps.append((m.created_at - last_out).total_seconds() / 60)
            last_out = None
    return round(sum(gaps) / len(gaps)) if gaps else None


def _conversation_ids(db: Session, supplier_id: int) -> list[int]:
    return list(db.scalars(select(SupplierConversation.id).where(SupplierConversation.supplier_id == supplier_id)))


def _messages(db: Session, supplier_id: int, limit: int = 300) -> list[SupplierMessage]:
    conv_ids = _conversation_ids(db, supplier_id)
    cond = SupplierMessage.supplier_id == supplier_id
    if conv_ids:
        cond = or_(cond, SupplierMessage.conversation_id.in_(conv_ids))
    rows = db.scalars(select(SupplierMessage).where(cond, SupplierMessage.direction != MD.MANAGER_IN)
                      .order_by(SupplierMessage.id.desc()).limit(limit))
    return list(rows)[::-1]


def _status(m: SupplierMessage) -> str:
    if m.error:
        return "FAILED"
    return "SENT" if m.telegram_message_id is not None else "SANDBOX"


def _chips(out: dict | None, cr_by_conv: dict, conv_id: int | None) -> list[dict]:
    """Data hasil ekstraksi agent (balasan PO atau misi) sebagai chip di gelembung supplier."""
    if not out:
        return []
    if out.get("source") == "hub_mission":
        res, chips = out.get("result") or {}, []
        for it in res.get("items") or []:
            name = it.get("material_ref") or "Item"
            conf = res.get("confidence", "MEDIUM")
            if it.get("price_per_unit") is not None:
                chips.append({"label": f"Harga {name}", "value": A.rupiah(it["price_per_unit"]), "confidence": conf})
            if it.get("lead_time_days") is not None:
                chips.append({"label": "Lead time", "value": f"{it['lead_time_days']} hari", "confidence": conf})
            if it.get("qty_available") is not None:
                chips.append({"label": f"Stok {name}", "value": A.fmt_qty(it["qty_available"]), "confidence": conf})
            if it.get("ready_date"):
                chips.append({"label": "Siap", "value": it["ready_date"], "confidence": conf})
        if res.get("promised_date"):
            chips.append({"label": "Janji kirim", "value": res["promised_date"], "confidence": res.get("confidence", "MEDIUM")})
        if res.get("decision") in ("declined",):
            chips.append({"label": "Keputusan", "value": "Menolak", "confidence": "HIGH"})
        for c in chips:
            c["mission_id"] = out.get("mission_id")
        return chips
    if "decision" not in out:
        return []
    cr_id = cr_by_conv.get(conv_id) if out["decision"] == "change_requested" else None
    approval = f"cr-{cr_id}" if cr_id else None
    chips = [{"label": "Keputusan", "value": DECISION_LABEL.get(out["decision"], out["decision"]), "confidence": "HIGH",
              "approval_id": approval}]
    if out.get("promised_delivery_date"):
        chips.append({"label": "Janji kirim", "value": out["promised_delivery_date"], "confidence": "HIGH"})
    if out.get("supplier_reference"):
        chips.append({"label": "Ref. supplier", "value": out["supplier_reference"], "confidence": "HIGH"})
    for ch in out.get("proposed_changes") or []:
        chips.append({"label": f"Revisi {ch.get('material_ref')}",
                      "value": f"{FIELD_LABEL.get(ch.get('field'), ch.get('field'))} {ch.get('new_value')}",
                      "confidence": "MEDIUM", "approval_id": approval})
    return chips


def _po_pdf(out: dict) -> list[dict]:
    """PDF PO final yang dikirim agent ke supplier (disimpan di `po_revisions`, bukan di Dokumen)."""
    if out.get("source") != "po_pdf" or not out.get("po_id"):
        return []
    return [{"id": f"rev-{out['revision_id']}", "kind": "pdf", "name": out.get("file_name") or "PO.pdf",
             "size": "PDF", "po_id": out["po_id"], "revision_id": out["revision_id"], "outbound": True}]


def _approval_from_buttons(buttons: list | None) -> str | None:
    for b in buttons or []:
        parts = str(b.get("data", "")).split(":")
        if len(parts) == 3 and parts[0] == "cr":
            return f"cr-{parts[1]}"
    return None


def thread_messages(db: Session, sup: Supplier) -> list[dict]:
    conv_ids = _conversation_ids(db, sup.id)
    cr_by_conv = {cr.conversation_id: cr.id for cr in db.scalars(
        select(POChangeRequest).where(POChangeRequest.conversation_id.in_(conv_ids)).order_by(POChangeRequest.id))} \
        if conv_ids else {}
    docs = {}
    for d in db.scalars(select(HubDocument).where(HubDocument.supplier_id == sup.id, HubDocument.message_id.isnot(None))):
        docs.setdefault(d.message_id, []).append({"id": f"doc-{d.id}", "doc_id": d.id, "kind": d.kind, "name": d.file_name,
                                                  "size": _size(d.size)})
    items, last_in = [], None
    for m in _messages(db, sup.id):
        out = m.agent_output or {}
        if m.direction == MD.MANAGER_OUT:
            first = (m.text or "").strip().splitlines()[0][:140] if m.text else ""
            items.append({"id": str(m.id), "from": "SYSTEM", "at": C.iso(m.created_at), "kind": "manager",
                          "text": f"Agent menghubungi manajer: {first}", "approval_id": _approval_from_buttons(m.buttons),
                          "manager_message_id": m.id})
            continue
        view = {"id": str(m.id), "message_id": m.id, "at": C.iso(m.created_at), "text": m.text,
                "attachments": docs.get(m.id, []) + _po_pdf(out), "extracted": [], "conversation_id": m.conversation_id}
        if m.direction == MD.IN:
            view.update({"from": "SUPPLIER", "status": None})
            last_in = view
        else:
            admin = out.get("source") == "hub_admin"
            view.update({"from": "ADMIN" if admin else "AGENT", "status": _status(m), "error": m.error,
                         "author": out.get("author"), "template": out.get("source") in ("hub_mission", "hub_template"),
                         "mission_id": out.get("mission_id")})
            chips = _chips(out, cr_by_conv, m.conversation_id)
            if chips:
                (last_in or view)["extracted"].extend(chips)
        items.append(view)
    for d in db.scalars(select(HubOutbox).where(HubOutbox.supplier_id == sup.id, HubOutbox.status == OutboxStatus.DRAFT)):
        items.append({"id": f"draft-{d.id}", "outbox_id": d.id, "from": "AGENT", "at": C.iso(d.created_at), "text": d.text,
                      "status": "DRAFT", "review_reason": d.review_reason, "attachments": [], "extracted": [],
                      "template": d.kind in ("mission", "reminder")})
    for a in db.scalars(select(HubAuditLog).where(HubAuditLog.ref_type == "supplier", HubAuditLog.ref_id == str(sup.id),
                                                  HubAuditLog.action.in_(tuple(SYSTEM_ACTIONS)))):
        items.append({"id": f"audit-{a.id}", "from": "SYSTEM", "at": C.iso(a.at), "kind": a.action,
                      "text": SYSTEM_ACTIONS[a.action].format(actor=a.actor, **(a.detail or {}))})
    items.sort(key=lambda x: (x["at"] or "", x["id"]))
    return items


def _size(n: int) -> str:
    return f"{n / 1048576:.1f} MB".replace(".", ",") if n > 1048576 else f"{max(1, round(n / 1024))} KB"


def _summary(db: Session, sup: Supplier) -> dict:
    ctl = db.scalar(select(HubSupplierControl).where(HubSupplierControl.supplier_id == sup.id))
    msgs = _messages(db, sup.id, limit=60)
    visible = [m for m in msgs if m.direction in (MD.IN, MD.OUT)]
    last = visible[-1] if visible else None
    drafts = list(db.scalars(select(HubOutbox).where(HubOutbox.supplier_id == sup.id, HubOutbox.status == OutboxStatus.DRAFT)
                             .order_by(HubOutbox.id)))
    seen = ctl.last_seen_message_id if ctl else 0
    last_view = None
    if drafts:
        last_view = {"from": "AGENT", "status": "DRAFT", "text": drafts[-1].text}
    elif last is not None:
        last_view = {"from": "SUPPLIER" if last.direction == MD.IN else
                     ("ADMIN" if (last.agent_output or {}).get("source") == "hub_admin" else "AGENT"),
                     "status": None if last.direction == MD.IN else _status(last), "text": last.text}
    times = [m.created_at for m in msgs] + [d.created_at for d in drafts]
    return {"id": sup.id, "supplier": supplier_view(db, sup), "mode": (ctl.mode if ctl else ThreadMode.AGENT).value,
            "unread": sum(1 for m in msgs if m.direction == MD.IN and m.id > seen),
            "refs": [p.po_number for p in db.scalars(select(PurchaseOrder).where(
                PurchaseOrder.supplier_id == sup.id, PurchaseOrder.status.in_(OPEN_PO)).order_by(PurchaseOrder.id).limit(3))],
            "last": last_view, "last_at": C.iso(max(times)) if times else None,
            "drafts": len(drafts), "failed": sum(1 for m in msgs if m.direction == MD.OUT and m.error)}


def list_threads(db: Session) -> list[dict]:
    ids = set(db.scalars(select(SupplierMessage.supplier_id).where(SupplierMessage.supplier_id.isnot(None)).distinct()))
    ids |= set(db.scalars(select(SupplierConversation.supplier_id).distinct()))
    ids |= set(db.scalars(select(HubOutbox.supplier_id).where(HubOutbox.status == OutboxStatus.DRAFT).distinct()))
    ids |= set(db.scalars(select(HubMissionTarget.supplier_id).distinct()))
    rows = [_summary(db, db.get(Supplier, i)) for i in ids if db.get(Supplier, i) is not None]
    db.commit()
    return sorted(rows, key=lambda r: r["last_at"] or "", reverse=True)


def get_thread(db: Session, supplier_id: int, mark_seen: bool = True) -> dict:
    sup = _supplier(db, supplier_id)
    ctl = C.control(db, sup.id)
    messages = thread_messages(db, sup)
    if mark_seen:
        last_in = max((m["message_id"] for m in messages if m.get("from") == "SUPPLIER"), default=0)
        ctl.last_seen_message_id = max(ctl.last_seen_message_id, last_in)
    data = {"id": sup.id, "supplier": supplier_view(db, sup), "mode": ctl.mode.value, "taken_over_by": ctl.taken_over_by,
            "taken_over_at": C.iso(ctl.taken_over_at), "messages": messages, "context": _context(db, sup)}
    db.commit()
    return data


def _context(db: Session, sup: Supplier) -> dict:
    from app.hub import approvals, missions
    pos = []
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.supplier_id == sup.id, PurchaseOrder.status.in_(OPEN_PO))
                         .order_by(PurchaseOrder.id.desc()).limit(8)):
        conf = A.confirmation(db, po.id)
        pos.append({"id": po.id, "po_number": po.po_number, "status": po.status.value, "confirmation": conf.status.value})
    ms = [missions.mission_brief(m) for m in db.scalars(
        select(HubMission).join(HubMissionTarget).where(HubMissionTarget.supplier_id == sup.id)
        .order_by(HubMission.id.desc()).limit(6))]
    crs = [approvals.cr_brief(cr) for cr in db.scalars(select(POChangeRequest).where(POChangeRequest.supplier_id == sup.id)
                                                       .order_by(POChangeRequest.id.desc()).limit(6))]
    mission_ids = [m["id"] for m in ms]
    props = [approvals.proposal_brief(p) for p in db.scalars(select(HubProposal).where(
        or_(HubProposal.supplier_id == sup.id, HubProposal.mission_id.in_(mission_ids or [-1])))
        .order_by(HubProposal.id.desc()).limit(6))]
    free = "Kirim langsung (setelah ambil alih)"
    return {"pos": pos, "missions": ms, "approvals": crs + props,
            "rules": [{"label": "Agent PO", "value": "Otomatis (konfirmasi & revisi)"},
                      {"label": "Pesan misi", "value": "Sesuai otonomi misi"},
                      {"label": "Pesan bebas", "value": free},
                      {"label": "Perubahan data", "value": "Selalu perlu persetujuan"}]}


# ---------------------------------------- actions ----------------------------------------
def takeover(db: Session, supplier_id: int, actor: str) -> None:
    _supplier(db, supplier_id)
    ctl = C.control(db, supplier_id)
    if ctl.mode == ThreadMode.HUMAN:
        raise AppError(409, f"Percakapan sudah diambil alih oleh {ctl.taken_over_by}")
    ctl.mode, ctl.taken_over_by, ctl.taken_over_at = ThreadMode.HUMAN, actor, A.now()
    C.audit(db, actor, "takeover", "supplier", supplier_id)
    db.commit()


def release(db: Session, supplier_id: int, actor: str) -> None:
    ctl = C.control(db, supplier_id)
    ctl.mode, ctl.taken_over_by, ctl.taken_over_at = ThreadMode.AGENT, None, None
    C.audit(db, actor, "release", "supplier", supplier_id)
    db.commit()


def _active_conversation_id(db: Session, supplier_id: int) -> int | None:
    return db.scalar(select(SupplierConversation.id).where(SupplierConversation.supplier_id == supplier_id,
                                                           SupplierConversation.status.in_(A.ACTIVE_CONVERSATION))
                     .order_by(SupplierConversation.id))


def _chat_or_409(svc, db: Session, supplier_id: int) -> int:
    chat_id = svc.supplier_chat_id(db, supplier_id)
    if chat_id is None:
        raise AppError(409, "Supplier belum terhubung ke Telegram")
    return chat_id


def send_manual(svc, db: Session, supplier_id: int, text: str, actor: str) -> dict:
    """Pesan bebas admin; hanya setelah thread diambil alih supaya tidak bertabrakan dengan agent."""
    _supplier(db, supplier_id)
    if not C.is_human(db, supplier_id):
        raise AppError(409, "Ambil alih percakapan dulu sebelum mengirim pesan manual")
    chat_id = _chat_or_409(svc, db, supplier_id)
    msg = svc.send(db, chat_id, text, direction=MD.OUT, supplier_id=supplier_id,
                   conversation_id=_active_conversation_id(db, supplier_id),
                   agent_output={"source": "hub_admin", "author": actor})
    C.audit(db, actor, "send_message", "supplier", supplier_id)
    db.commit()
    return {"id": msg.id, "error": msg.error}


def send_outbox(svc, db: Session, outbox_id: int, actor: str, text: str | None = None) -> dict:
    d = db.get(HubOutbox, outbox_id)
    if d is None:
        raise AppError(404, "Draf tidak ditemukan")
    if d.status != OutboxStatus.DRAFT:
        raise AppError(409, "Draf sudah diproses")
    if C.is_paused(db):
        raise AppError(409, "Agent sedang dijeda. Lanjutkan Agent untuk mengirim pesan.")
    chat_id = _chat_or_409(svc, db, d.supplier_id)
    target = db.get(HubMissionTarget, d.mission_target_id) if d.mission_target_id else None
    body = (text or d.text).strip()
    if len(body) < 2:
        raise AppError(422, "Pesan terlalu pendek")
    out = {"source": "hub_mission" if target else "hub_template", "kind": d.kind, "reviewed_by": actor}
    if target is not None:
        out.update({"mission_id": target.mission_id, "target_id": target.id})
    msg = svc.send(db, chat_id, body, direction=MD.OUT, supplier_id=d.supplier_id, agent_output=out)
    db.flush()
    d.status, d.text, d.sent_message_id, d.reviewed_by = OutboxStatus.SENT, body, msg.id, actor
    if target is not None and target.state in (TargetState.QUEUED, TargetState.PAUSED) and d.kind == "mission":
        target.state, target.sent_at, target.last_message_id = TargetState.SENT, A.now(), msg.id
    C.audit(db, actor, "send_draft", "outbox", d.id, supplier_id=d.supplier_id)
    db.commit()
    return {"id": msg.id, "error": msg.error}


def discard_outbox(db: Session, outbox_id: int, actor: str) -> None:
    d = db.get(HubOutbox, outbox_id)
    if d is None or d.status != OutboxStatus.DRAFT:
        raise AppError(409, "Draf sudah diproses")
    d.status, d.reviewed_by = OutboxStatus.DISCARDED, actor
    C.audit(db, actor, "discard_draft", "supplier", d.supplier_id, outbox_id=d.id)
    db.commit()


def retry_message(svc, db: Session, message_id: int, actor: str) -> dict:
    m = db.get(SupplierMessage, message_id)
    if m is None or m.direction != MD.OUT or not m.error:
        raise AppError(409, "Hanya pesan keluar yang gagal yang dapat dikirim ulang")
    supplier_id = m.supplier_id or (db.get(SupplierConversation, m.conversation_id).supplier_id if m.conversation_id else None)
    chat_id = _chat_or_409(svc, db, supplier_id)
    try:
        m.telegram_message_id = svc.transport.send(chat_id, m.text, m.buttons)
        m.chat_id, m.error = chat_id, None
    except Exception as e:  # noqa: BLE001
        m.error = f"{type(e).__name__}: {e}"[:300]
    C.audit(db, actor, "retry_message", "message", m.id)
    db.commit()
    if m.error:
        raise AppError(502, f"Pengiriman ulang gagal: {m.error}")
    return {"id": m.id}


def missions_for_supplier_active(db: Session, supplier_id: int) -> list[HubMissionTarget]:
    return list(db.scalars(select(HubMissionTarget).join(HubMission).where(
        HubMissionTarget.supplier_id == supplier_id, HubMission.status == MissionStatus.ACTIVE)))
