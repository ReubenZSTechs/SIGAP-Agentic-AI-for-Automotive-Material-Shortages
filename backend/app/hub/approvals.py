"""Inbox Persetujuan: `po_change_requests` (revisi PO dari agent Telegram) + `hub_proposals` (hasil misi).

Keputusan revisi PO dijalankan lewat `manager_graph` yang sama dengan tombol Telegram, jadi aturan
bisnis, validasi snapshot basi, dan pesan ke supplier tetap satu jalur.
"""
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (BOMItem, HubAuditLog, HubProposal, POChangeRequest, POItem, POSupplierConfirmation,
                        PurchaseOrder, Supplier, SupplierMessage)
from app.models.enums import ChangeRequestStatus, MessageDirection, POStatus
from app.models.hub import ProposalStatus, ProposalType
from app.hub import common as C
from app.services import master_service
from configs.tools import po_actions as A

CRS = ChangeRequestStatus
CR_PENDING = (CRS.PENDING_MANAGER, CRS.AWAITING_MANAGER_CONFIRM)
CR_STATUS = {CRS.PENDING_MANAGER: "PENDING", CRS.AWAITING_MANAGER_CONFIRM: "PENDING", CRS.CHANGE_APPROVED: "APPROVED",
             CRS.ABORTED: "APPROVED", CRS.RESOURCED: "APPROVED", CRS.EXPIRED: "EXPIRED", CRS.FAILED: "FAILED"}
CHOICE_LABEL = {"abort": "Batalkan PO", "approve_change": "Setujui perubahan", "resource": "Pesan ke supplier lain"}
CR_FIELD = {"qty_ordered": ("qty", "qty", "higher-better"), "unit_price": ("harga", "Rp", "lower-better"),
            "needed_by_date": ("tanggal", "date", "lower-better")}
OPEN_PO_STATUSES = (POStatus.DRAFT, POStatus.PENDING_APPROVAL, POStatus.APPROVED, POStatus.ISSUED,
                    POStatus.PARTIALLY_RECEIVED)


def _clock(dt) -> str:
    return C.short_local(dt) if dt else ""


def _hub_decider(db: Session, ref: str) -> HubAuditLog | None:
    return db.scalar(select(HubAuditLog).where(HubAuditLog.ref_type == "change_request", HubAuditLog.ref_id == ref,
                                               HubAuditLog.action == "choose").order_by(HubAuditLog.id.desc()))


# ------------------------------------------- views -------------------------------------------
def cr_brief(cr: POChangeRequest) -> dict:
    return {"id": f"cr-{cr.id}", "title": f"Revisi {cr.po_number}", "status": CR_STATUS[cr.status], "type": "PO_REVISION"}


def proposal_brief(p: HubProposal) -> dict:
    return {"id": f"hp-{p.id}", "title": p.title, "status": p.status.value, "type": p.type.value}


def cr_view(db: Session, cr: POChangeRequest) -> dict:
    snap = cr.po_snapshot
    po = db.get(PurchaseOrder, cr.po_id) if cr.po_id else None
    pending = cr.status in CR_PENDING
    stale = pending and (po is None or not A._unchanged(po, snap))
    rows = []
    for c in cr.proposed_changes:
        label, unit, direction = CR_FIELD.get(c["field"], (c["field"], "text", "neutral"))
        rows.append({"key": f"{c['po_item_id']}:{c['field']}", "label": f"{c['sku']} {c['name']} · {label}",
                     "before": c["old"], "after": c["new"], "unit": unit, "direction": direction})
    for c in cr.invalid_changes or []:
        rows.append({"key": f"invalid:{c.get('material_ref')}:{c.get('field')}",
                     "label": f"{c.get('material_ref')} · {c.get('field')} (tidak valid: {c.get('error')})",
                     "before": None, "after": c.get("new_value"), "unit": "text", "direction": "neutral"})
    approve = next((o for o in cr.options if o["key"] == "approve_change"), None)
    impact_items = [{"label": "Total PO", "before": A.rupiah(approve["total_before"]), "after": A.rupiah(approve["total_after"])}] \
        if approve else []
    risk = "HIGH" if any(r["direction"] != "neutral" and r["unit"] in ("qty", "date") for r in rows) else "MEDIUM"
    if approve and approve["total_before"]:
        pct = abs(approve["total_after"] - approve["total_before"]) / approve["total_before"] * 100
        if pct > C.threshold(db, "price_change_pct_high"):
            risk = "HIGH"
    hub = _hub_decider(db, str(cr.id))
    decided_by = hub.actor if hub else ("Manajer via Telegram" if cr.decided_at else None)
    note = CHOICE_LABEL.get(cr.manager_choice) if cr.manager_choice else (cr.result or {}).get("error")
    return {
        "id": f"cr-{cr.id}", "type": "PO_REVISION", "status": CR_STATUS[cr.status], "risk": risk, "version": 1,
        "stale": stale, "title": f"Revisi {cr.po_number}", "supplier": {"id": cr.supplier_id, "name": cr.supplier.name},
        "created_at": C.iso(cr.created_at), "expires_at": C.iso(C.after(cr.created_at, C.cr_ttl_hours())),
        "summary": f"Supplier meminta revisi {cr.po_number} (total saat ini {A.rupiah(snap['total_amount'])}). "
                   "Pilih salah satu opsi; keputusan berlaku sama seperti tombol di Telegram manajer.",
        "thread_id": cr.supplier_id, "po_id": cr.po_id, "po_number": cr.po_number,
        "diff": {"rows": rows},
        "evidence": [{"id": f"cr{cr.id}", "from": cr.supplier.name, "at": _clock(cr.created_at), "confidence": "HIGH",
                      "excerpt": cr.supplier_message}],
        "impact": {"summary": "PO hanya berubah bila Anda memilih opsi. Opsi dihitung oleh sistem, bukan oleh AI.",
                   "items": impact_items},
        "options": [{"key": o["key"], "label": o["label"], "effect": o["effect"],
                     "total_before": o.get("total_before"), "total_after": o.get("total_after"),
                     "purchase_orders": [{"supplier_name": g["supplier_name"], "total_amount": g["total_amount"]}
                                         for g in o.get("purchase_orders", [])]} for o in cr.options],
        "decided_by": decided_by, "decided_at": C.iso(cr.decided_at), "decision_note": note,
    }


def _price_impact(db: Session, material_ids: list[int]) -> str:
    if not material_ids:
        return ""
    n_po = db.scalar(select(func.count(func.distinct(POItem.po_id))).join(PurchaseOrder).where(
        POItem.material_id.in_(material_ids), PurchaseOrder.status.in_(OPEN_PO_STATUSES))) or 0
    n_bom = db.scalar(select(func.count(func.distinct(BOMItem.parent_id))).where(BOMItem.child_id.in_(material_ids))) or 0
    return f"{n_bom} BOM dan {n_po} PO terbuka memakai material ini. PO yang sudah ada tidak diubah; harga baru dipakai untuk PO berikutnya."


def _current_price(db: Session, material_id: int, supplier_id: int) -> int | None:
    from app.models import MaterialSupplier
    return db.scalar(select(MaterialSupplier.unit_price).where(MaterialSupplier.material_id == material_id,
                                                               MaterialSupplier.supplier_id == supplier_id))


def proposal_view(db: Session, p: HubProposal) -> dict:
    payload = p.payload
    rows = payload["diff"]["rows"]
    stale = False
    if p.status == ProposalStatus.PENDING and p.type == ProposalType.PRICE_UPDATE:
        stale = any(_current_price(db, r["meta"]["material_id"], r["meta"]["supplier_id"]) != r["before"] for r in rows)
    impact = dict(payload.get("impact") or {"summary": "", "items": []})
    if p.type == ProposalType.PRICE_UPDATE:
        impact["summary"] = _price_impact(db, sorted({r["meta"]["material_id"] for r in rows}))
    po_changed = False
    if p.po_id is None and payload.get("po_snapshot"):
        po_changed = True
    elif p.po_id and payload.get("po_snapshot"):
        po = db.get(PurchaseOrder, p.po_id)
        po_changed = po is None or not A._unchanged(po, payload["po_snapshot"])
    sup = db.get(Supplier, p.supplier_id) if p.supplier_id else None
    return {
        "id": f"hp-{p.id}", "type": p.type.value, "status": p.status.value, "risk": p.risk, "version": p.version,
        "stale": stale, "po_changed": po_changed, "title": p.title,
        "supplier": {"id": sup.id, "name": sup.name} if sup else {"name": payload.get("supplier_label", "Beberapa supplier")},
        "created_at": C.iso(p.created_at), "expires_at": C.iso(p.expires_at), "summary": payload.get("summary", ""),
        "mission_id": p.mission_id, "po_id": p.po_id, "thread_id": p.supplier_id,
        "diff": {"rows": [{k: v for k, v in r.items() if k != "meta"} for r in rows]},
        "evidence": payload.get("evidence", []), "impact": impact,
        "decided_by": p.decided_by, "decided_at": C.iso(p.decided_at), "decision_note": p.decision_note,
    }


def _expire(db: Session) -> None:
    for p in db.scalars(select(HubProposal).where(HubProposal.status == ProposalStatus.PENDING,
                                                  HubProposal.expires_at < A.now())):
        p.status = ProposalStatus.EXPIRED


def list_approvals(db: Session) -> list[dict]:
    _expire(db)
    crs = list(db.scalars(select(POChangeRequest).order_by(POChangeRequest.id.desc()).limit(100)))
    props = list(db.scalars(select(HubProposal).order_by(HubProposal.id.desc()).limit(100)))
    out = [cr_view(db, c) for c in crs] + [proposal_view(db, p) for p in props]
    db.commit()
    return sorted(out, key=lambda x: x["created_at"] or "", reverse=True)


def pending_count(db: Session) -> int:
    return (db.scalar(select(func.count(POChangeRequest.id)).where(POChangeRequest.status.in_(CR_PENDING))) or 0) + \
        (db.scalar(select(func.count(HubProposal.id)).where(HubProposal.status == ProposalStatus.PENDING,
                                                            HubProposal.expires_at >= A.now())) or 0)


def parse_id(approval_id: str) -> tuple[str, int]:
    kind, _, num = approval_id.partition("-")
    if kind not in ("cr", "hp") or not num.isdigit():
        raise AppError(404, "Item persetujuan tidak ditemukan")
    return kind, int(num)


def get_approval(db: Session, approval_id: str) -> dict:
    kind, num = parse_id(approval_id)
    obj = db.get(POChangeRequest if kind == "cr" else HubProposal, num)
    if obj is None:
        raise AppError(404, "Item persetujuan tidak ditemukan")
    return cr_view(db, obj) if kind == "cr" else proposal_view(db, obj)


# ----------------------------------------- decisions -----------------------------------------
def choose_change_request(svc, cr_id: int, choice: str, actor: str) -> dict:
    """Pilihan opsi revisi PO dari Hub = tombol `cr:<id>:<choice>` milik manajer, dengan actor dari Hub."""
    from app.database import SessionLocal
    with SessionLocal() as db:
        cr = db.get(POChangeRequest, cr_id)
        if cr is None:
            raise AppError(404, "Permintaan revisi tidak ditemukan")
        if cr.status not in CR_PENDING:
            raise AppError(409, f"Permintaan revisi #{cr_id} sudah diproses ({cr.status.value})")
        if choice not in {o["key"] for o in cr.options}:
            raise AppError(422, f"Opsi '{choice}' tidak tersedia untuk permintaan revisi #{cr_id}")
        po_number = cr.po_number
        db.add(SupplierMessage(chat_id=svc.manager_chat_id, direction=MessageDirection.MANAGER_IN,
                               text=f"[Hub] {actor}: {CHOICE_LABEL.get(choice, choice)} ({po_number})",
                               agent_output={"source": "hub", "author": actor, "button": f"cr:{cr_id}:{choice}"}))
        C.audit(db, actor, "choose", "change_request", cr_id, choice=choice, po_number=po_number)
        db.commit()
    svc.mirror_to_manager(f"Diputuskan via Hub oleh {actor}: {CHOICE_LABEL.get(choice, choice)} untuk {po_number}.")
    result = svc.manager_graph.invoke({"kind": "button", "data": f"cr:{cr_id}:{choice}", "actor": f"{actor} via Hub"})
    if result.get("error"):
        raise AppError(409, result["error"])
    return result


def _proposal(db: Session, pid: int) -> HubProposal:
    p = db.get(HubProposal, pid)
    if p is None:
        raise AppError(404, "Item persetujuan tidak ditemukan")
    if p.status != ProposalStatus.PENDING:
        raise AppError(409, "Item sudah diputuskan")
    if p.expires_at < A.now():
        p.status = ProposalStatus.EXPIRED
        db.commit()
        raise AppError(409, "Item sudah kedaluwarsa. Buat misi baru untuk meminta data terbaru.")
    return p


def approve_proposal(pid: int, body: dict) -> dict:
    actor = C.require_actor(body.get("approver"))
    with A.write_session() as db:
        p = _proposal(db, pid)
        if body.get("version") != p.version:
            raise AppError(409, "Data berubah sejak diajukan. Muat ulang kartu.")
        rows = p.payload["diff"]["rows"]
        selected = set(body.get("selected") or [r["key"] for r in rows])
        edits = body.get("edits") or {}
        applied = []
        if p.type == ProposalType.PRICE_UPDATE:
            chosen = [r for r in rows if r["key"] in selected]
            if not chosen:
                raise AppError(422, "Pilih minimal satu baris untuk disetujui")
            for r in chosen:
                m = r["meta"]
                current = _current_price(db, m["material_id"], m["supplier_id"])
                if current != r["before"]:
                    raise AppError(409, f"Harga {r['label']} berubah sejak diajukan (sekarang {A.rupiah(current or 0)}). "
                                        "Tolak kartu ini lalu buat misi baru.")
                price = edits.get(r["key"], r["after"])
                if not isinstance(price, (int, float)) or price < 0:
                    raise AppError(422, f"Harga baru {r['label']} tidak valid")
                data = {"unit_price": int(round(price))}
                if m.get("lead_time_days") is not None:
                    data["lead_time_days"] = int(m["lead_time_days"])
                if current is None:
                    master_service.add_link(db, m["material_id"], {"supplier_id": m["supplier_id"], "moq": 1,
                                                                   "lead_time_days": data.get("lead_time_days", 0),
                                                                   "unit_price": data["unit_price"]})
                else:
                    master_service.update_link(db, m["material_id"], m["supplier_id"], data)
                applied.append({"key": r["key"], **data})
        elif p.type == ProposalType.PO_DELAY:
            for r in rows:
                if r["key"] not in selected:
                    continue
                po = db.get(PurchaseOrder, r["meta"]["po_id"])
                if po is None:
                    raise AppError(409, "PO sudah dihapus")
                conf = A.confirmation(db, po.id)
                conf.promised_delivery_date = date.fromisoformat(r["after"])
                conf.note = f"Jadwal kirim diperbarui via Hub oleh {actor}"[:300]
                applied.append({"key": r["key"], "po_number": po.po_number, "promised_delivery_date": r["after"]})
        else:   # STOCK_CHECK: hasil dicatat, tidak ada data master yang berubah
            applied = [{"key": r["key"]} for r in rows if r["key"] in selected]
        p.status, p.decided_by, p.decided_at = ProposalStatus.APPROVED, actor, A.now()
        p.result = {"applied": applied}
        C.audit(db, actor, "approve", "proposal", p.id, type=p.type.value, applied=applied)
        return proposal_view(db, p)


def decide_proposal(pid: int, mode: str, body: dict) -> dict:
    actor = C.require_actor(body.get("approver"))
    reason = (body.get("reason") or "").strip()
    if len(reason) < 3:
        raise AppError(422, "Alasan/catatan wajib diisi (min. 3 karakter)")
    with A.write_session() as db:
        p = _proposal(db, pid)
        p.status = ProposalStatus.REJECTED if mode == "reject" else ProposalStatus.REVISION
        p.decided_by, p.decided_at, p.decision_note = actor, A.now(), reason[:300]
        C.audit(db, actor, mode, "proposal", p.id, reason=reason)
        return proposal_view(db, p)


def po_supplier_confirmation(db: Session, po_id: int) -> POSupplierConfirmation | None:
    return db.scalar(select(POSupplierConfirmation).where(POSupplierConfirmation.po_id == po_id))
