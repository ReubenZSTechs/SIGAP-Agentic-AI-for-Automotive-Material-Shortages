"""Misi multi-supplier: penawaran harga, cek stok, konfirmasi jadwal kirim, minta dokumen.

- Pesan pembuka diisi template oleh KODE (angka selalu dari database, bukan dari LLM).
- Satu supplier hanya punya satu topik aktif: target misi menunggu selama supplier punya percakapan
  PO terbuka (agent PO lama tidak diubah), lalu ditanyakan setelah percakapan itu selesai.
- Balasan supplier diklasifikasi `mission_reply_agent`; hasilnya menjadi proposal di Inbox Persetujuan.
- Misi tidak pernah membuat/mengubah/menghapus PO. Data PO hanya dibaca sebagai sumber misi.
"""
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.database import SessionLocal
from app.models import (HubMission, HubMissionTarget, HubOutbox, HubProposal, Material, MaterialSupplier,
                        PurchaseOrder, Supplier, SupplierConversation, SupplierMessage, SupplierTelegramLink)
from app.models.enums import ItemCategory, MessageDirection, POStatus
from app.models.hub import (MissionScenario, MissionSource, MissionStatus, OutboxStatus, ProposalStatus,
                            ProposalType, TargetState)
from app.hub import common as C
from app.services import master_service
from configs.tools import po_actions as A

log = logging.getLogger(__name__)
MD, TS, SC = MessageDirection, TargetState, MissionScenario
TERMINAL = (TS.REPLIED, TS.NO_REPLY, TS.ESCALATED)
WAITING = (TS.SENT, TS.PAUSED)
ALLOWED_PO = {
    SC.PRICE_QUOTE: (POStatus.DRAFT, POStatus.PENDING_APPROVAL, POStatus.APPROVED, POStatus.REJECTED, POStatus.ISSUED,
                     POStatus.PARTIALLY_RECEIVED, POStatus.RECEIVED),
    SC.STOCK_CHECK: (POStatus.DRAFT, POStatus.PENDING_APPROVAL, POStatus.APPROVED, POStatus.ISSUED),
    SC.DELIVERY_CONFIRM: (POStatus.ISSUED, POStatus.PARTIALLY_RECEIVED),
    SC.DOC_REQUEST: (POStatus.ISSUED, POStatus.PARTIALLY_RECEIVED, POStatus.RECEIVED),
}
PO_SUPPLIER_ONLY = (SC.DELIVERY_CONFIRM, SC.DOC_REQUEST)
TITLE = {SC.PRICE_QUOTE: "Penawaran harga", SC.STOCK_CHECK: "Cek stok", SC.DELIVERY_CONFIRM: "Konfirmasi jadwal kirim",
         SC.DOC_REQUEST: "Minta dokumen"}
DAYS = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def deadline_text(dt) -> str:
    local = dt.replace(tzinfo=C.ZoneInfo("UTC")).astimezone(C.TZ)
    return f"{DAYS[local.weekday()]}, {local.day} {MONTHS[local.month - 1]} pukul {local.strftime('%H.%M')}"


# ------------------------------------------- options -------------------------------------------
def _supplier_brief(db: Session, sup: Supplier) -> dict:
    link = db.scalar(select(SupplierTelegramLink).where(SupplierTelegramLink.supplier_id == sup.id))
    from app.models import HubSupplierControl
    ctl = db.scalar(select(HubSupplierControl).where(HubSupplierControl.supplier_id == sup.id))
    state, sandbox = C.telegram_state(link, ctl)
    return {"id": sup.id, "code": sup.code, "name": sup.name, "contact": C.contact_name(sup), "telegram": state,
            "sandbox": sandbox, "is_active": sup.is_active}


def mission_options(db: Session) -> dict:
    materials = []
    for m in db.scalars(select(Material).where(Material.category == ItemCategory.PURCHASED, Material.is_active)
                        .order_by(Material.sku)):
        links = [l for l in master_service.list_links(db, m.id) if l["is_active"]]
        materials.append({"id": m.id, "sku": m.sku, "name": m.name, "uom": m.uom,
                          "suppliers": [{"supplier_id": l["supplier_id"], "unit_price": l["unit_price"],
                                         "lead_time_days": l["lead_time_days"]} for l in links]})
    pos = [{"id": p.id, "po_number": p.po_number, "status": p.status.value, "supplier_name": p.supplier.name,
            "total_amount": p.total_amount}
           for p in db.scalars(select(PurchaseOrder).where(PurchaseOrder.status != POStatus.CANCELLED)
                               .order_by(PurchaseOrder.id.desc()).limit(60))]
    suppliers = [_supplier_brief(db, s) for s in db.scalars(select(Supplier).order_by(Supplier.name))]
    db.commit()
    return {"materials": materials, "suppliers": suppliers, "pos": pos}


def po_options(db: Session, po_id: int) -> dict:
    """Prefill misi dari PO: item, supplier PO, supplier alternatif per item, dan skenario yang valid."""
    po = db.get(PurchaseOrder, po_id)
    if po is None:
        raise AppError(404, "Purchase Order tidak ditemukan")
    snap = A.po_snapshot(po)
    alts: dict[int, set] = {}
    for it in po.items:
        for l in A.active_links(db, it.material_id):
            if l["supplier_id"] != po.supplier_id:
                alts.setdefault(l["supplier_id"], set()).add(it.sku)
    suppliers = [{**_supplier_brief(db, po.supplier), "role": "PO", "skus": [i.sku for i in po.items]}]
    for sid, skus in sorted(alts.items()):
        suppliers.append({**_supplier_brief(db, db.get(Supplier, sid)), "role": "ALT", "skus": sorted(skus)})
    open_conv = C.has_open_po_conversation(db, po.supplier_id)
    scenarios = [{"key": s.value, "allowed": po.status in ALLOWED_PO[s],
                  "blocked_reason": ("Percakapan Telegram untuk PO supplier ini masih berjalan"
                                     if s in PO_SUPPLIER_ONLY and open_conv and po.status in ALLOWED_PO[s] else None)}
                 for s in SC]
    db.commit()
    return {"po": snap, "suppliers": suppliers, "scenarios": scenarios,
            "items": [{"material_id": i["material_id"], "sku": i["sku"], "name": i["name"], "qty": i["qty_ordered"],
                       "uom": i["uom"], "needed_by": i["needed_by_date"]} for i in snap["items"]]}


# -------------------------------------------- views --------------------------------------------
def _items_label(m: HubMission) -> str:
    if m.topic and not m.items:
        return m.topic
    if len(m.items) == 1:
        it = m.items[0]
        return it["name"] + (f" · {A.fmt_qty(it['qty'])} {it['uom']}" if it.get("qty") else "")
    return f"{len(m.items)} item" + (f" ({m.po_snapshot['po_number']})" if m.po_snapshot else "")


def _step(m: HubMission) -> int:
    if m.status == MissionStatus.DONE:
        return 5
    if m.status == MissionStatus.SUMMARIZING:
        return 4
    return 2 if any(t.state == TS.QUEUED for t in m.targets) else 3


def target_summary(m: HubMission, t: HubMissionTarget) -> str | None:
    res = t.result or {}
    if not res.get("decision") and not res.get("documents"):
        return None
    if res.get("decision") == "declined":
        return "Menolak" + (f": {res['notes']}" if res.get("notes") else "")
    if res.get("documents"):
        return f"{len(res['documents'])} dokumen diterima"
    parts = []
    for it in res.get("items") or []:
        bits = []
        if it.get("price_per_unit") is not None:
            bits.append(A.rupiah(it["price_per_unit"]))
        if it.get("lead_time_days") is not None:
            bits.append(f"{it['lead_time_days']} hari")
        if it.get("qty_available") is not None:
            bits.append(f"stok {A.fmt_qty(it['qty_available'])}")
        if it.get("ready_date"):
            bits.append(f"siap {it['ready_date']}")
        if bits:
            prefix = f"{it['material_ref']}: " if len(m.items) > 1 and it.get("material_ref") else ""
            parts.append(prefix + " · ".join(bits))
    if res.get("promised_date"):
        parts.append(f"janji kirim {res['promised_date']}")
    return "; ".join(parts) or res.get("notes") or "Dibalas"


def mission_brief(m: HubMission) -> dict:
    replied = sum(1 for t in m.targets if t.state == TS.REPLIED)
    return {"id": m.id, "number": m.id, "title": m.title, "status": m.status.value, "replied": replied, "total": len(m.targets)}


def _waiting_reason(db: Session, m: HubMission, t: HubMissionTarget, has_draft: bool) -> str | None:
    """Kenapa target belum terkirim (ditampilkan di tabel misi)."""
    if m.status != MissionStatus.ACTIVE or t.state not in (TS.QUEUED, TS.PAUSED) or has_draft:
        return None
    if C.is_paused(db):
        return "Agent dijeda"
    if C.has_open_po_conversation(db, t.supplier_id):
        return "Menunggu percakapan PO selesai"
    if (t.result or {}).get("not_linked"):
        return "Telegram belum terhubung"
    if _busy_with_other_mission(db, t):
        return "Menunggu misi lain dengan supplier ini"
    return None if C.within_working_hours(db) else "Di luar jam kerja"


def mission_view(db: Session, m: HubMission) -> dict:
    drafts = {d.mission_target_id for d in db.scalars(select(HubOutbox).where(
        HubOutbox.status == OutboxStatus.DRAFT, HubOutbox.mission_target_id.in_([t.id for t in m.targets] or [-1])))}
    props = list(db.scalars(select(HubProposal).where(HubProposal.mission_id == m.id).order_by(HubProposal.id)))
    first = props[0] if props else None
    items = m.items or []
    return {
        "id": m.id, "number": m.id, "scenario": m.scenario.value, "title": m.title, "source": m.source.value,
        "po_id": m.po_id, "po_number": (m.po_snapshot or {}).get("po_number"), "item": _items_label(m),
        "qty": items[0]["qty"] if len(items) == 1 else None, "uom": items[0]["uom"] if len(items) == 1 else None,
        "items": items, "topic": m.topic, "status": m.status.value, "step": _step(m), "deadline": C.iso(m.deadline),
        "autonomy": m.autonomy, "created_by": m.created_by, "created_at": C.iso(m.created_at), "summary": m.summary,
        "replied": sum(1 for t in m.targets if t.state == TS.REPLIED), "total": len(m.targets),
        "targets": [{"supplier_id": t.supplier_id, "supplier": _supplier_brief(db, t.supplier), "thread_id": t.supplier_id,
                     "state": t.state.value, "waiting": _waiting_reason(db, m, t, t.id in drafts), "sent_at": C.iso(t.sent_at), "replied_at": C.iso(t.replied_at),
                     "reminded_at": C.iso(t.reminded_at), "result": target_summary(m, t), "draft": t.id in drafts}
                    for t in m.targets],
        "approval": {"id": f"hp-{first.id}", "title": first.title, "status": first.status.value} if first else None,
        "proposals": [{"id": f"hp-{p.id}", "title": p.title, "status": p.status.value} for p in props],
    }


def list_missions(db: Session) -> list[dict]:
    return [mission_view(db, m) for m in db.scalars(select(HubMission).order_by(HubMission.id.desc()).limit(200))]


def get_mission(db: Session, mission_id: int) -> dict:
    m = db.get(HubMission, mission_id)
    if m is None:
        raise AppError(404, "Misi tidak ditemukan")
    return mission_view(db, m)


def po_context(db: Session, po_id: int) -> dict:
    """Panel read-only di detail PO: misi, percakapan Telegram, proposal yang terkait PO ini."""
    from app.hub.approvals import CR_STATUS, proposal_brief
    from app.models import POChangeRequest
    missions = [mission_brief(m) | {"scenario": m.scenario.value, "summary": m.summary}
                for m in db.scalars(select(HubMission).where(HubMission.po_id == po_id).order_by(HubMission.id.desc()))]
    convs = [{"id": c.id, "purpose": c.purpose.value, "status": c.status.value, "supplier_id": c.supplier_id,
              "last_activity_at": C.iso(c.last_activity_at or c.created_at)}
             for c in db.scalars(select(SupplierConversation).where(SupplierConversation.po_id == po_id)
                                 .order_by(SupplierConversation.id.desc()))]
    crs = [{"id": f"cr-{c.id}", "title": f"Revisi {c.po_number}", "status": CR_STATUS[c.status]}
           for c in db.scalars(select(POChangeRequest).where(POChangeRequest.po_id == po_id))]
    props = [proposal_brief(p) for p in db.scalars(select(HubProposal).where(HubProposal.po_id == po_id))]
    conf = db.scalar(select(A.POSupplierConfirmation).where(A.POSupplierConfirmation.po_id == po_id))
    return {"missions": missions, "conversations": convs, "approvals": crs + props,
            "confirmation": {"status": conf.status.value, "promised_delivery_date": A._iso(conf.promised_delivery_date),
                             "supplier_reference": conf.supplier_reference} if conf else None}


# ------------------------------------------- create -------------------------------------------
def create_mission(db: Session, body: dict) -> HubMission:
    actor = C.require_actor(body.get("approver"))
    try:
        scenario = SC(body.get("scenario"))
    except ValueError as e:
        raise AppError(422, "Skenario misi tidak dikenal") from e
    deadline = C.parse_dt(str(body.get("deadline") or ""))
    if deadline <= A.now():
        raise AppError(422, "Tenggat harus di masa depan")
    autonomy = body.get("autonomy") or C.outbound(db, scenario.value)
    if autonomy not in ("AUTO", "REVIEW"):
        raise AppError(422, "Otonomi harus AUTO atau REVIEW")
    message = (body.get("message") or "").strip() or C.template_for(db, scenario.value)
    supplier_ids = list(dict.fromkeys(int(s) for s in body.get("supplier_ids") or []))
    if not supplier_ids:
        raise AppError(422, "Pilih minimal satu supplier")
    topic = (body.get("topic") or "").strip() or None
    source, po, snap, items = MissionSource.MATERIAL, None, None, []

    if body.get("po_id"):
        source = MissionSource.PO
        po = db.get(PurchaseOrder, int(body["po_id"]))
        if po is None:
            raise AppError(404, "Purchase Order tidak ditemukan")
        if po.status not in ALLOWED_PO[scenario]:
            raise AppError(400, f"Skenario {TITLE[scenario]} tidak berlaku untuk PO berstatus {po.status.value}")
        snap = A.po_snapshot(po)
        if scenario in PO_SUPPLIER_ONLY:
            if supplier_ids != [po.supplier_id]:
                raise AppError(400, f"{TITLE[scenario]} hanya dikirim ke supplier PO ({po.supplier.name})")
            if C.has_open_po_conversation(db, po.supplier_id):
                raise AppError(409, f"Percakapan Telegram untuk PO {po.supplier.name} masih berjalan. "
                                    "Tunggu sampai selesai agar balasan supplier tidak tertukar.")
        wanted = {int(i["material_id"]) for i in body.get("items") or []} or {i["material_id"] for i in snap["items"]}
        items = [{"material_id": i["material_id"], "sku": i["sku"], "name": i["name"], "qty": i["qty_ordered"],
                  "uom": i["uom"], "needed_by": i["needed_by_date"]} for i in snap["items"] if i["material_id"] in wanted]
        if scenario == SC.DOC_REQUEST and not topic:
            topic = f"invoice dan surat jalan {po.po_number}"
    else:
        if scenario == SC.DELIVERY_CONFIRM:
            raise AppError(400, "Konfirmasi jadwal kirim harus dibuat dari PO")
        for raw in body.get("items") or []:
            mat = db.get(Material, int(raw["material_id"]))
            if mat is None or mat.category != ItemCategory.PURCHASED:
                raise AppError(422, "Material beli tidak ditemukan")
            qty = raw.get("qty")
            if scenario in (SC.PRICE_QUOTE, SC.STOCK_CHECK) and (qty is None or float(qty) <= 0):
                raise AppError(422, f"Qty {mat.name} harus lebih dari 0")
            items.append({"material_id": mat.id, "sku": mat.sku, "name": mat.name, "qty": float(qty) if qty else None,
                          "uom": mat.uom, "needed_by": raw.get("needed_by")})
        if scenario in (SC.PRICE_QUOTE, SC.STOCK_CHECK) and not items:
            raise AppError(422, "Pilih minimal satu material")
        if scenario == SC.DOC_REQUEST and not topic:
            raise AppError(422, "Isi topik dokumen yang diminta")
    if scenario in (SC.PRICE_QUOTE, SC.STOCK_CHECK) and not items:
        raise AppError(422, "Pilih minimal satu item PO")
    for sid in supplier_ids:
        if db.get(Supplier, sid) is None:
            raise AppError(404, f"Supplier {sid} tidak ditemukan")

    label = topic or (items[0]["name"] if len(items) == 1 else f"{len(items)} item {snap['po_number']}" if snap else f"{len(items)} item")
    m = HubMission(scenario=scenario, title=(body.get("title") or f"{TITLE[scenario]} {label}")[:160], source=source,
                   po_id=po.id if po else None, po_snapshot=snap, items=items, topic=topic, message_template=message,
                   deadline=deadline, autonomy=autonomy, status=MissionStatus.ACTIVE, created_by=actor,
                   summary="Menunggu giliran pengiriman ke supplier.")
    m.targets = [HubMissionTarget(supplier_id=sid, state=TS.QUEUED) for sid in supplier_ids]
    db.add(m)
    db.flush()
    C.audit(db, actor, "create_mission", "mission", m.id, scenario=scenario.value, suppliers=supplier_ids, po_id=m.po_id)
    db.commit()
    return m


# ------------------------------------------ messages ------------------------------------------
def _item_values(m: HubMission) -> dict:
    if m.topic and (not m.items or m.scenario == SC.DOC_REQUEST):
        return {"item": m.topic, "qty": "", "satuan": ""}
    if len(m.items) == 1:
        it = m.items[0]
        qty = f" sebanyak {A.fmt_qty(it['qty'])} {it['uom']}" if it.get("qty") else ""
        return {"item": f"{it['name']}{qty}", "qty": A.fmt_qty(it["qty"]) if it.get("qty") else "", "satuan": it["uom"]}
    return {"item": "item-item berikut", "qty": "", "satuan": ""}


def compose(m: HubMission, sup: Supplier, template: str | None = None) -> str:
    """Isi template + blok data deterministik (daftar item tanpa harga, atau ringkasan PO untuk supplier PO)."""
    values = {"waktu": C.greeting(), "kontak": C.contact_name(sup), "supplier": sup.name, "perusahaan": C.COMPANY,
              "tenggat": deadline_text(m.deadline), "po": (m.po_snapshot or {}).get("po_number", ""), **_item_values(m)}
    text = C.fill(template or m.message_template, values)
    if m.scenario in PO_SUPPLIER_ONLY and m.po_snapshot:
        return f"{text}\n\n{A.po_summary_text(m.po_snapshot)}"
    if m.scenario in (SC.PRICE_QUOTE, SC.STOCK_CHECK) and (len(m.items) > 1 or m.po_snapshot):
        lines = [f"{n}. {it['sku']} {it['name']} — {A.fmt_qty(it['qty'])} {it['uom']}"
                 + (f" · dibutuhkan {it['needed_by']}" if it.get("needed_by") else "")
                 for n, it in enumerate(m.items, 1)]
        return text + "\n\nDaftar item:\n" + "\n".join(lines)
    return text


def _out(m: HubMission, t: HubMissionTarget, kind: str, **extra) -> dict:
    return {"source": "hub_mission", "mission_id": m.id, "target_id": t.id, "kind": kind, **extra}


def _queue_or_send(svc, db: Session, m: HubMission, t: HubMissionTarget, text: str, kind: str, review: bool,
                   reason: str, sends: list[dict]) -> str:
    """REVIEW -> draf di hub_outbox (satu draf per target & jenis); AUTO -> dikirim setelah commit."""
    if review:
        exists = db.scalar(select(HubOutbox.id).where(HubOutbox.mission_target_id == t.id, HubOutbox.kind == kind,
                                                      HubOutbox.status == OutboxStatus.DRAFT))
        if exists is None:
            db.add(HubOutbox(supplier_id=t.supplier_id, mission_target_id=t.id, kind=kind, text=text, review_reason=reason))
        return "draft"
    sends.append({"chat_id": svc.supplier_chat_id(db, t.supplier_id), "text": text, "direction": MD.OUT,
                  "supplier_id": t.supplier_id, "agent_output": _out(m, t, kind)})
    return "sent"


def _busy_with_other_mission(db: Session, t: HubMissionTarget) -> bool:
    return db.scalar(select(HubMissionTarget.id).join(HubMission).where(
        HubMissionTarget.supplier_id == t.supplier_id, HubMissionTarget.id != t.id,
        HubMissionTarget.state == TS.SENT, HubMission.status == MissionStatus.ACTIVE).limit(1)) is not None


# -------------------------------------------- tick --------------------------------------------
def tick(svc) -> dict:
    """Satu putaran dispatcher Hub (worker / POST /hub/dispatch / setelah misi dibuat)."""
    sends, notices, counts = [], [], {"sent": 0, "drafted": 0, "paused": 0, "reminded": 0, "no_reply": 0, "summarized": 0}
    with SessionLocal() as db:
        paused = C.is_paused(db)
        can_send = not paused and C.within_working_hours(db)
        now = A.now()
        remind_h, escalate_h = C.threshold(db, "reminder_after_hours"), C.threshold(db, "escalate_after_hours")
        reminder_review = C.outbound(db, "REMINDER") == "REVIEW"
        for m in db.scalars(select(HubMission).where(HubMission.status == MissionStatus.ACTIVE).order_by(HubMission.id)):
            if m.deadline < now:
                _close(db, m, "deadline")
                counts["summarized"] += 1
                continue
            for t in m.targets:
                if t.state in (TS.QUEUED, TS.PAUSED):
                    if not can_send or C.has_open_po_conversation(db, t.supplier_id) or _busy_with_other_mission(db, t):
                        continue
                    if svc.supplier_chat_id(db, t.supplier_id) is None:
                        t.result = {**(t.result or {}), "not_linked": True}
                        continue
                    sup = db.get(Supplier, t.supplier_id)
                    text = compose(m, sup) if t.state == TS.QUEUED else \
                        "Melanjutkan permintaan kami sebelumnya:\n\n" + compose(m, sup)
                    how = _queue_or_send(svc, db, m, t, text, "mission", m.autonomy == "REVIEW",
                                         'Misi diatur "Draf dulu"', sends)
                    if how == "sent":
                        t.state, t.sent_at = TS.SENT, now
                        counts["sent"] += 1
                    else:
                        counts["drafted"] += 1
                elif t.state == TS.SENT:
                    if C.has_open_po_conversation(db, t.supplier_id, active_only=True):
                        t.state = TS.PAUSED
                        counts["paused"] += 1
                    elif t.sent_at < now - timedelta(hours=escalate_h):
                        t.state = TS.NO_REPLY
                        counts["no_reply"] += 1
                        notices.append(f"Misi #{m.id} ({m.title}): {db.get(Supplier, t.supplier_id).name} belum membalas "
                                       f"setelah {int(escalate_h)} jam. Tandai eskalasi dari Hub bila perlu.")
                    elif can_send and t.reminded_at is None and t.sent_at < now - timedelta(hours=remind_h):
                        sup = db.get(Supplier, t.supplier_id)
                        text = compose(m, sup, C.template_for(db, "REMINDER"))
                        _queue_or_send(svc, db, m, t, text, "reminder", reminder_review, 'Pengingat diatur "Draf dulu"', sends)
                        t.reminded_at = now
                        counts["reminded"] += 1
            if m.status == MissionStatus.ACTIVE and m.targets and all(t.state in TERMINAL for t in m.targets):
                summarize(db, m)
                counts["summarized"] += 1
        db.commit()
    svc.deliver(sends)
    if notices:
        svc.deliver([svc.manager_send(n) for n in notices])
    return counts


def _close(db: Session, m: HubMission, reason: str) -> None:
    for t in m.targets:
        if t.state not in TERMINAL:
            t.state = TS.NO_REPLY
    for d in db.scalars(select(HubOutbox).where(HubOutbox.status == OutboxStatus.DRAFT,
                                                HubOutbox.mission_target_id.in_([t.id for t in m.targets] or [-1]))):
        d.status = OutboxStatus.DISCARDED
    m.status = MissionStatus.SUMMARIZING
    summarize(db, m)
    m.summary = (m.summary or "") + (" Ditutup karena melewati tenggat." if reason == "deadline" else "")


# ------------------------------------------ actions ------------------------------------------
def _mission(db: Session, mission_id: int, active: bool = True) -> HubMission:
    m = db.get(HubMission, mission_id)
    if m is None:
        raise AppError(404, "Misi tidak ditemukan")
    if active and m.status != MissionStatus.ACTIVE:
        raise AppError(409, "Misi sudah ditutup")
    return m


def remind(svc, mission_id: int, supplier_ids: list[int] | None, actor: str) -> dict:
    sends = []
    with SessionLocal() as db:
        m = _mission(db, mission_id)
        if C.is_paused(db):
            raise AppError(409, "Agent sedang dijeda. Lanjutkan Agent untuk mengirim pengingat.")
        review = C.outbound(db, "REMINDER") == "REVIEW"
        count = 0
        for t in m.targets:
            if t.state not in (TS.SENT, TS.NO_REPLY) or (supplier_ids and t.supplier_id not in supplier_ids):
                continue
            text = compose(m, db.get(Supplier, t.supplier_id), C.template_for(db, "REMINDER"))
            _queue_or_send(svc, db, m, t, text, "reminder", review, 'Pengingat diatur "Draf dulu"', sends)
            t.reminded_at = A.now()
            if t.state == TS.NO_REPLY:
                t.state = TS.SENT
            count += 1
        C.audit(db, actor, "remind", "mission", m.id, count=count)
        db.commit()
    svc.deliver(sends)
    return {"count": count, "drafted": review}


def escalate(svc, mission_id: int, supplier_id: int, actor: str) -> None:
    with SessionLocal() as db:
        m = _mission(db, mission_id)
        t = next((x for x in m.targets if x.supplier_id == supplier_id), None)
        if t is None:
            raise AppError(404, "Supplier tidak ada di misi ini")
        sup = db.get(Supplier, supplier_id)
        t.state = TS.ESCALATED
        text = (f"Selamat {C.greeting()} {C.contact_name(sup)}, permintaan kami terkait {_item_values(m)['item']} belum "
                f"mendapat balasan. Mohon konfirmasi hari ini agar kami bisa menyesuaikan rencana produksi. Terima kasih.")
        db.add(HubOutbox(supplier_id=supplier_id, mission_target_id=t.id, kind="escalation", text=text,
                         review_reason="Eskalasi selalu perlu review"))
        C.audit(db, actor, "escalate", "supplier", supplier_id, mission=m.id)
        if all(x.state in TERMINAL for x in m.targets):
            summarize(db, m)
        name, title = sup.name, m.title
        db.commit()
    svc.deliver([svc.manager_send(f"Eskalasi Misi #{mission_id} ({title}): {name} belum membalas. Ditandai oleh {actor} "
                                  "via Hub; draf pesan eskalasi menunggu review.")])


def close(mission_id: int, actor: str) -> None:
    with SessionLocal() as db:
        m = _mission(db, mission_id)
        _close(db, m, "manual")
        C.audit(db, actor, "close_mission", "mission", m.id)
        db.commit()


def cancel(mission_id: int, actor: str) -> None:
    with SessionLocal() as db:
        m = _mission(db, mission_id)
        m.status, m.closed_at, m.summary = MissionStatus.CANCELLED, A.now(), f"Dibatalkan oleh {actor}."
        for d in db.scalars(select(HubOutbox).where(HubOutbox.status == OutboxStatus.DRAFT,
                                                    HubOutbox.mission_target_id.in_([t.id for t in m.targets]))):
            d.status = OutboxStatus.DISCARDED
        C.audit(db, actor, "cancel_mission", "mission", m.id)
        db.commit()


# ---------------------------------------- inbound reply ----------------------------------------
def waiting_target(db: Session, supplier_id: int) -> HubMissionTarget | None:
    return db.scalar(select(HubMissionTarget).join(HubMission).where(
        HubMissionTarget.supplier_id == supplier_id, HubMissionTarget.state.in_((TS.SENT, TS.PAUSED, TS.NO_REPLY)),
        HubMission.status == MissionStatus.ACTIVE).order_by(HubMissionTarget.sent_at.desc().nullslast()).limit(1))


def route_reply(svc, supplier_id: int, chat_id: int, text: str, message_id: int) -> dict | None:
    """Balasan supplier tanpa percakapan PO aktif -> misi yang sedang menunggu jawabannya (bila ada)."""
    if "mission_reply_agent" not in svc.agents:
        return None
    with SessionLocal() as db:
        t = waiting_target(db, supplier_id)
        if t is None or t.sent_at is None:
            return None
        m = t.mission
        recent = [{"direction": x.direction.value, "text": x.text} for x in db.scalars(
            select(SupplierMessage).where(SupplierMessage.supplier_id == supplier_id, SupplierMessage.id < message_id,
                                          SupplierMessage.created_at >= t.sent_at - timedelta(minutes=1),
                                          SupplierMessage.direction.in_((MD.OUT, MD.IN)))
            .order_by(SupplierMessage.id.desc()).limit(10))][::-1]
        payload = {"scenario": m.scenario.value, "supplier_name": db.get(Supplier, supplier_id).name,
                   "items": [{k: it.get(k) for k in ("sku", "name", "qty", "uom", "needed_by")} for it in m.items],
                   "topic": m.topic, "po_number": (m.po_snapshot or {}).get("po_number"),
                   "deadline": deadline_text(m.deadline), "conversation": recent, "latest_supplier_message": text}
        target_id = t.id
    out = svc.run_agent("mission_reply_agent", payload)
    with SessionLocal() as db:
        t = db.get(HubMissionTarget, target_id)
        m = t.mission
        if out["decision"] in ("answered", "declined"):
            t.state, t.replied_at = TS.REPLIED, A.now()
            t.result = {k: v for k, v in out.items() if k != "reply_text"}
        if m.status == MissionStatus.ACTIVE and all(x.state in TERMINAL for x in m.targets):
            summarize(db, m)
        state, mission_id = t.state.value, m.id
        send = {"chat_id": chat_id, "text": out["reply_text"], "direction": MD.OUT, "supplier_id": supplier_id,
                "agent_output": _out(m, t, "reply", result=out)}
        db.commit()
    svc.deliver([send])
    return {"handled": True, "mission_id": mission_id, "target_state": state, "decision": out["decision"]}


def attach_documents(db: Session, supplier_id: int, doc_ids: list[int]) -> HubMission | None:
    """Dokumen masuk saat ada misi DOC_REQUEST yang menunggu -> target dianggap sudah membalas."""
    t = db.scalar(select(HubMissionTarget).join(HubMission).where(
        HubMissionTarget.supplier_id == supplier_id, HubMissionTarget.state.in_((TS.SENT, TS.PAUSED, TS.NO_REPLY)),
        HubMission.status == MissionStatus.ACTIVE, HubMission.scenario == SC.DOC_REQUEST).limit(1))
    if t is None:
        return None
    t.state, t.replied_at = TS.REPLIED, A.now()
    t.result = {"decision": "answered", "documents": [*(t.result or {}).get("documents", []), *doc_ids]}
    m = t.mission
    if all(x.state in TERMINAL for x in m.targets):
        summarize(db, m)
    return m


# ------------------------------------------ summary ------------------------------------------
def _match_item(m: HubMission, ref: str | None) -> dict | None:
    if len(m.items) == 1:
        return m.items[0]
    ref = (ref or "").strip().lower()
    return next((it for it in m.items if ref and (it["sku"].lower() == ref or ref in it["name"].lower()
                                                  or it["name"].lower() in ref)), None)


def _evidence(db: Session, m: HubMission, t: HubMissionTarget) -> dict | None:
    msg = db.scalar(select(SupplierMessage).where(SupplierMessage.supplier_id == t.supplier_id,
                                                  SupplierMessage.direction == MD.IN,
                                                  SupplierMessage.created_at >= (t.sent_at or m.created_at) - timedelta(minutes=1))
                    .order_by(SupplierMessage.id.desc()).limit(1))
    if msg is None:
        return None
    return {"id": f"m{msg.id}", "message_id": msg.id, "from": t.supplier.name, "at": C.short_local(msg.created_at),
            "confidence": (t.result or {}).get("confidence", "MEDIUM"), "excerpt": msg.text[:300]}


def _proposal(db: Session, m: HubMission, ptype: ProposalType, title: str, rows: list[dict], evidence: list[dict],
              risk: str, summary: str, supplier_id: int | None = None, label: str | None = None) -> None:
    hours = C.expiry_hours(db, m.scenario.value, 24)
    db.add(HubProposal(type=ptype, status=ProposalStatus.PENDING, risk=risk, version=1, mission_id=m.id,
                       supplier_id=supplier_id, po_id=m.po_id, title=title[:160], expires_at=A.now() + timedelta(hours=hours),
                       payload={"summary": summary, "diff": {"rows": rows}, "evidence": evidence,
                                "impact": {"summary": "", "items": []}, "po_snapshot": m.po_snapshot,
                                "supplier_label": label}))


def summarize(db: Session, m: HubMission) -> None:
    """Rangkum balasan -> proposal untuk Inbox Persetujuan, lalu misi selesai."""
    m.status, m.closed_at = MissionStatus.DONE, A.now()
    replied = [t for t in m.targets if t.state == TS.REPLIED and (t.result or {}).get("decision") != "declined"]
    declined = [t for t in m.targets if (t.result or {}).get("decision") == "declined"]
    head = f"{len(replied)} dari {len(m.targets)} supplier menjawab" + (f", {len(declined)} menolak" if declined else "") + "."
    evidence = [e for e in (_evidence(db, m, t) for t in replied) if e]
    pct_high = C.threshold(db, "price_change_pct_high")

    if m.scenario == SC.PRICE_QUOTE:
        rows, best = [], None
        for t in replied:
            for it in t.result.get("items") or []:
                item = _match_item(m, it.get("material_ref"))
                if item is None or it.get("price_per_unit") is None:
                    continue
                before = db.scalar(select(MaterialSupplier.unit_price).where(
                    MaterialSupplier.material_id == item["material_id"], MaterialSupplier.supplier_id == t.supplier_id))
                rows.append({"key": f"{item['material_id']}:{t.supplier_id}",
                             "label": f"{t.supplier.name} · {item['name']}" + ("" if before is not None else " (supplier baru)"),
                             "before": before, "after": int(it["price_per_unit"]), "unit": "Rp", "direction": "lower-better",
                             "editable": True, "meta": {"material_id": item["material_id"], "supplier_id": t.supplier_id,
                                                        "lead_time_days": it.get("lead_time_days")}})
                if best is None or it["price_per_unit"] < best[1]:
                    best = (t.supplier.name, it["price_per_unit"], item["name"])
        if rows:
            changes = [abs(r["after"] - r["before"]) / r["before"] * 100 for r in rows if r["before"]]
            risk = "HIGH" if any(c > pct_high for c in changes) else \
                "MEDIUM" if any(r["before"] is None or r["after"] > r["before"] for r in rows) else "LOW"
            _proposal(db, m, ProposalType.PRICE_UPDATE, f"Update harga {_items_label(m)}", rows, evidence, risk,
                      f"Agent meminta penawaran ke {len(m.targets)} supplier (Misi #{m.id}). {head} "
                      "Centang baris yang ingin diterapkan ke master harga material-supplier.",
                      supplier_id=rows[0]["meta"]["supplier_id"] if len({r['meta']['supplier_id'] for r in rows}) == 1 else None,
                      label=f"{len({r['meta']['supplier_id'] for r in rows})} supplier")
            head += f" Penawaran terendah: {best[0]} {A.rupiah(best[1])} untuk {best[2]}."
    elif m.scenario == SC.STOCK_CHECK:
        rows, short = [], False
        for t in replied:
            for it in t.result.get("items") or []:
                item = _match_item(m, it.get("material_ref"))
                if item is None:
                    continue
                if it.get("qty_available") is not None:
                    short = short or (item.get("qty") or 0) > it["qty_available"]
                    rows.append({"key": f"{item['material_id']}:{t.supplier_id}:qty", "label": f"{t.supplier.name} · {item['name']} (qty)",
                                 "before": item.get("qty"), "after": it["qty_available"], "unit": "qty",
                                 "direction": "higher-better", "meta": {"supplier_id": t.supplier_id}})
                if it.get("ready_date"):
                    rows.append({"key": f"{item['material_id']}:{t.supplier_id}:ready", "label": f"{t.supplier.name} · {item['name']} (siap)",
                                 "before": item.get("needed_by"), "after": it["ready_date"], "unit": "date",
                                 "direction": "lower-better", "meta": {"supplier_id": t.supplier_id}})
        if rows:
            _proposal(db, m, ProposalType.STOCK_CHECK, f"Konfirmasi stok {_items_label(m)}", rows, evidence,
                      "MEDIUM" if short else "LOW",
                      f"Hasil cek stok Misi #{m.id}. {head} Menyetujui hanya mencatat hasil; PO dan master tidak berubah.",
                      label=f"{len(replied)} supplier")
    elif m.scenario == SC.DELIVERY_CONFIRM and m.po_snapshot:
        for t in replied:
            promised = t.result.get("promised_date")
            if not promised:
                continue
            conf = db.scalar(select(A.POSupplierConfirmation).where(A.POSupplierConfirmation.po_id == m.po_id)) if m.po_id else None
            needs = [i["needed_by_date"] for i in m.po_snapshot["items"] if i.get("needed_by_date")]
            before = A._iso(conf.promised_delivery_date) if conf and conf.promised_delivery_date else (max(needs) if needs else None)
            if before is None or promised > before:
                from datetime import date
                days = (date.fromisoformat(promised) - date.fromisoformat(before)).days if before else 0
                rows = [{"key": f"po:{m.po_id}", "label": f"Janji kirim {m.po_snapshot['po_number']}", "before": before,
                         "after": promised, "unit": "date", "direction": "lower-better", "meta": {"po_id": m.po_id}}]
                _proposal(db, m, ProposalType.PO_DELAY, f"Keterlambatan {m.po_snapshot['po_number']}", rows, evidence,
                          "HIGH" if days > C.threshold(db, "delay_days_high") else "MEDIUM",
                          f"{t.supplier.name} mengabarkan jadwal kirim {promised}. Menyetujui memperbarui tanggal janji kirim "
                          "pada konfirmasi PO; isi PO tidak berubah.", supplier_id=t.supplier_id)
                head += f" Jadwal mundur ke {promised}."
            else:
                head += f" Jadwal sesuai ({promised})."
    elif m.scenario == SC.DOC_REQUEST:
        n = sum(len((t.result or {}).get("documents") or []) for t in m.targets)
        head += f" {n} dokumen diterima; validasi di tab Dokumen."
    m.summary = head[:500]
