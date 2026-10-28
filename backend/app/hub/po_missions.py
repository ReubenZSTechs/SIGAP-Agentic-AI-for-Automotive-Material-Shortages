"""Misi PO: setiap percakapan agent PO (konfirmasi / pembatalan / revisi) tampil sebagai misi di Hub Supplier.

Dua arah:
- Agent -> misi: `ensure_po_mission` dipanggil dari `queue_conversation`, jadi SETIAP jalur yang menghubungi
  supplier tentang PO (otomasi chat Dashboard, approve PO, PO pengganti, tombol di detail PO) lebih dulu
  membuat misi; dispatcher baru mengirim pesan pembukanya setelah itu.
- Manajer -> agent: misi PO_CONFIRM / PO_CANCEL dari wizard membuka percakapan PO (`start_for_mission`);
  percakapan itu menempel ke misi yang sudah dibuat manajer.

Progres misi diturunkan dari status percakapan (`sync`), tidak disimpan dua kali.
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from app.hub.audit_log import AGENT_ACTOR, agent as audit_agent
from app.models import HubMission, HubMissionTarget, POChangeRequest, PurchaseOrder, Supplier, SupplierConversation
from app.models.enums import ChangeRequestStatus, ConversationPurpose, ConversationStatus
from app.models.hub import PO_SCENARIOS, MissionScenario, MissionSource, MissionStatus, TargetState
from configs.tools.po_common import now, po_snapshot

CS, TS, SC = ConversationStatus, TargetState, MissionScenario
SCENARIO_OF = {ConversationPurpose.CONFIRM_ORDER: SC.PO_CONFIRM, ConversationPurpose.REVISION_CONFIRM: SC.PO_CONFIRM,
               ConversationPurpose.CANCEL_ORDER: SC.PO_CANCEL}
TITLE = {SC.PO_CONFIRM: "Konfirmasi PO {po}", SC.PO_CANCEL: "Pembatalan PO {po}"}
AGENT_MESSAGE = "(pesan disusun agent PO)"
CLOSED_REASON = {"supplier_cancelled": "PO dibatalkan oleh supplier.",
                 "price_unreasonable": "PO dibatalkan agent: harga dari supplier tidak wajar (di luar batas pembatalan).", "aborted": "PO dibatalkan manajer.",
                 "resourced": "PO dialihkan ke supplier lain.", "po_changed": "PO berubah / tidak berlaku lagi.",
                 "po_deleted_before_dispatch": "PO dihapus sebelum dikirim.",
                 "superseded_by": "Diganti permintaan pembatalan PO."}


def _active_po_mission(db: Session, po_id: int, scenario: MissionScenario) -> HubMission | None:
    return db.scalar(select(HubMission).where(HubMission.po_id == po_id, HubMission.scenario == scenario,
                                              HubMission.status == MissionStatus.ACTIVE)
                     .order_by(HubMission.id.desc()).limit(1))


def ensure_po_mission(db: Session, conv: SupplierConversation, actor: str | None = None) -> HubMission:
    """Mission tracking `conv` (created when the PO has no active mission of that kind; else the conversation
    is attached to it, e.g. a revision confirmation continuing the same confirmation mission)."""
    scenario = SCENARIO_OF[conv.purpose]
    m = _active_po_mission(db, conv.po_id, scenario) if conv.po_id else None
    if m is None:
        po = db.get(PurchaseOrder, conv.po_id) if conv.po_id else None
        snap = po_snapshot(po) if po is not None else conv.po_snapshot
        sup = db.get(Supplier, conv.supplier_id)
        needs = [i["needed_by_date"] for i in snap["items"] if i.get("needed_by_date")]
        m = HubMission(scenario=scenario, title=TITLE[scenario].format(po=conv.po_number), source=MissionSource.PO,
                       po_id=conv.po_id, po_snapshot=snap, topic=None, message_template=AGENT_MESSAGE,
                       items=[{"material_id": i["material_id"], "sku": i["sku"], "name": i["name"], "qty": i["qty_ordered"],
                               "uom": i["uom"], "needed_by": i.get("needed_by_date")} for i in snap["items"]],
                       deadline=now() + timedelta(days=3), autonomy="AUTO", status=MissionStatus.ACTIVE,
                       automation_action_id=conv.automation_action_id, created_by=actor or AGENT_ACTOR,
                       summary=f"Agent akan menghubungi {sup.name} untuk "
                               + ("konfirmasi " if scenario == SC.PO_CONFIRM else "persetujuan pembatalan ")
                               + conv.po_number + (f" (dibutuhkan mulai {min(needs)})." if needs else "."))
        m.targets = [HubMissionTarget(supplier_id=conv.supplier_id, state=TS.QUEUED, conversation_id=conv.id)]
        db.add(m)
        db.flush()
        audit_agent(db, "create_mission", "mission", m.id,
                    f"Misi #{m.id} dibuat: {m.title} — agent menghubungi {sup.name} setelah misi tercatat",
                    supplier_id=conv.supplier_id, po_number=conv.po_number, scenario=scenario.value,
                    conversation=conv.id, automation_action=conv.automation_action_id)
        return m
    t = next((x for x in m.targets if x.supplier_id == conv.supplier_id), None)
    if t is None:
        t = HubMissionTarget(supplier_id=conv.supplier_id, state=TS.QUEUED)
        m.targets.append(t)
    t.conversation_id, t.state, t.replied_at = conv.id, TS.QUEUED, None
    if conv.purpose == ConversationPurpose.REVISION_CONFIRM:
        m.summary = f"Revisi {conv.po_number} disetujui; agent meminta supplier mengonfirmasi versi baru."
    db.flush()
    return m


def _open_cr(db: Session, conv: SupplierConversation) -> POChangeRequest | None:
    return db.scalar(select(POChangeRequest).where(
        POChangeRequest.conversation_id == conv.id,
        POChangeRequest.status.in_((ChangeRequestStatus.PENDING_MANAGER, ChangeRequestStatus.AWAITING_MANAGER_CONFIRM)))
        .limit(1))


def _finish(db: Session, m: HubMission, status: MissionStatus, summary: str) -> None:
    m.status, m.closed_at, m.summary = status, now(), summary[:500]
    audit_agent(db, "mission_done" if status == MissionStatus.DONE else "mission_cancelled", "mission", m.id,
                f"Misi #{m.id} {m.title}: {summary}", po_number=(m.po_snapshot or {}).get("po_number"),
                supplier_id=m.targets[0].supplier_id if m.targets else None)


def sync(db: Session) -> int:
    """Mirror PO conversation states into their missions. Returns the number of missions changed.

    Runs on every mission page load and worker tick, so it loads missions, targets, conversations and open
    change requests in 4 queries in total (no per-mission round trips)."""
    changed = 0
    missions = list(db.scalars(select(HubMission).options(selectinload(HubMission.targets))
                               .where(HubMission.status == MissionStatus.ACTIVE, HubMission.scenario.in_(PO_SCENARIOS))))
    conv_ids = {t.conversation_id for m in missions for t in m.targets if t.conversation_id}
    convs = {c.id: c for c in db.scalars(select(SupplierConversation).where(SupplierConversation.id.in_(conv_ids)))} \
        if conv_ids else {}
    open_crs = {cr.conversation_id: cr for cr in db.scalars(select(POChangeRequest).where(
        POChangeRequest.conversation_id.in_(conv_ids),
        POChangeRequest.status.in_((ChangeRequestStatus.PENDING_MANAGER, ChangeRequestStatus.AWAITING_MANAGER_CONFIRM))))} \
        if conv_ids else {}
    for m in missions:
        for t in m.targets:
            conv = convs.get(t.conversation_id) if t.conversation_id else None
            if conv is None:
                continue
            before = (t.state, m.status)
            po_number, outcome = conv.po_number, conv.outcome or {}
            if conv.status == CS.QUEUED:
                t.state = TS.QUEUED
            elif conv.status == CS.AWAITING_SUPPLIER:
                t.state, t.sent_at = TS.SENT, t.sent_at or conv.started_at
                if outcome.get("confirmed_pending"):
                    m.summary = f"Supplier sudah setuju; agent menunggu data konfirmasi {po_number} yang belum lengkap."
                else:
                    m.summary = f"Pesan terkirim; menunggu balasan supplier untuk {po_number}."
            elif conv.status == CS.REVISION_REQUESTED or conv.id in open_crs:
                t.state = TS.WAITING_MANAGER
                cr = open_crs.get(conv.id)
                m.summary = (f"Supplier meminta perubahan {po_number}; menunggu keputusan manajer"
                             + (f" (Persetujuan cr-{cr.id})." if cr else "."))
            elif conv.status == CS.CONFIRMED:
                t.state, t.replied_at = TS.REPLIED, conv.closed_at
                t.result = {"decision": "confirmed", "promised_date": outcome.get("promised_delivery_date"),
                            "notes": outcome.get("supplier_reference")}
                _finish(db, m, MissionStatus.DONE, f"{po_number} dikonfirmasi supplier"
                        + (f", janji kirim {outcome['promised_delivery_date']}" if outcome.get("promised_delivery_date") else "")
                        + ". PO final (PDF) terkirim.")
            elif conv.status == CS.CANCEL_CONFIRMED:
                t.state, t.replied_at = TS.REPLIED, conv.closed_at
                t.result = {"decision": "answered", "notes": "pembatalan disetujui"}
                _finish(db, m, MissionStatus.DONE, f"Supplier menyetujui pembatalan; {po_number} dibatalkan.")
            elif conv.status in (CS.DECLINED, CS.ESCALATED):
                t.state = TS.ESCALATED
                t.result = {"decision": "declined" if conv.status == CS.DECLINED else "unclear",
                            "notes": outcome.get("reason")}
                _finish(db, m, MissionStatus.DONE,
                        (f"Supplier menolak {po_number}" if conv.status == CS.DECLINED else f"{po_number} dieskalasi")
                        + f" ({outcome.get('reason') or 'lihat Chat Manajer'}); diteruskan ke manajer.")
            elif conv.status == CS.CLOSED:
                reason = outcome.get("result") or outcome.get("reason") or ("superseded_by" if outcome.get("superseded_by") else None)
                if reason == "change_approved":
                    continue                           # REVISION_CONFIRM berikutnya menempel di target ini
                t.state = TS.ESCALATED if reason not in ("supplier_cancelled", "price_unreasonable", "aborted",
                                                         "resourced") else TS.REPLIED
                _finish(db, m, MissionStatus.CANCELLED if reason != "resourced" else MissionStatus.DONE,
                        CLOSED_REASON.get(reason, f"Percakapan {po_number} ditutup ({reason or '-'})."))
            changed += before != (t.state, m.status)
    return changed


def start_for_mission(db: Session, m: HubMission, po: PurchaseOrder) -> SupplierConversation:
    """Manager-created PO mission: the agent opens the PO conversation (it attaches to `m`)."""
    from configs.tools.supplier_conversation import start_supplier_conversation
    purpose = ConversationPurpose.CONFIRM_ORDER if m.scenario == SC.PO_CONFIRM else ConversationPurpose.CANCEL_ORDER
    conv = start_supplier_conversation(db, po, purpose.value)
    m.summary = f"Agent membuka percakapan {purpose.value.replace('_', ' ').lower()} {po.po_number} dengan {po.supplier.name}."
    return conv


def waiting_reason(db: Session, t: HubMissionTarget) -> str | None:
    conv = db.get(SupplierConversation, t.conversation_id) if t.conversation_id else None
    if conv is None or conv.status != CS.QUEUED:
        return None
    if (conv.outcome or {}).get("not_linked_notified"):
        return "Telegram belum terhubung"
    return "Menunggu percakapan PO lain dengan supplier ini selesai"
