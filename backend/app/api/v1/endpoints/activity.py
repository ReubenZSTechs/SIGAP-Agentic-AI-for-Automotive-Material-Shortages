"""Riwayat Aktivitas: keputusan manajer + tindakan agent (`hub_audit_log`), untuk observabilitas agent.

Setiap baris dapat ditautkan ke panggilan LLM (`agent_runs`) dan tool (`tool_runs`) lewat `trace_id`.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import TranslatedRoute, get_db
from app.core.exceptions import AppError
from app.models import AgentRun, HubAuditLog, PurchaseOrder, Supplier, ToolRun

router = APIRouter(route_class=TranslatedRoute)       # teks tampilan Hub ikut bahasa pengguna

ACTION_LABEL = {
    # keputusan manajer
    "choose": "Memutuskan permintaan supplier", "approve": "Menyetujui ajuan", "reject": "Menolak ajuan",
    "revision": "Minta revisi ajuan", "approve_automation": "Menyetujui usulan chat", "reject_automation": "Menolak usulan chat",
    "update_policies": "Mengubah aturan otonomi", "pause": "Menjeda agent", "resume": "Melanjutkan agent",
    "takeover": "Mengambil alih percakapan", "release": "Menyerahkan ke agent", "send_draft": "Mengirim draf",
    "discard_draft": "Membuang draf", "send_manual": "Mengirim pesan manual", "remind": "Mengirim pengingat",
    "escalate": "Menandai eskalasi", "close_mission": "Menutup misi", "cancel_mission": "Membatalkan misi",
    "invite": "Mengundang supplier", "link_sandbox": "Menautkan sandbox", "start_conversation": "Memulai percakapan PO",
    "press_button": "Menekan tombol manajer",
    # tindakan agent
    "create_mission": "Membuat misi", "mission_done": "Misi selesai", "mission_cancelled": "Misi berhenti",
    "auto_accept_date": "Menerima tanggal kirim (dalam batas)", "auto_accept_price": "Menerima harga (dalam batas)", "auto_cancel_price": "Membatalkan PO (harga tidak wajar)",
    "escalate_date": "Tanggal kirim ke manajer", "escalate_change": "Perubahan PO ke manajer",
    "escalate_cancellation": "Pembatalan ke manajer", "supplier_cancelled": "PO dibatalkan supplier",
    "supplier_cancel_partial": "Pembatalan sebagian ke manajer", "replacement_po": "Menerbitkan PO pengganti",
    "po_confirmed": "PO dikonfirmasi supplier", "po_declined": "PO ditolak supplier",
    "guardrail_block": "Guardrail menolak pesan", "guardrail_alert": "Guardrail memberi tahu manajer",
}
DECISION_ACTIONS = ("choose", "approve", "reject", "revision", "approve_automation", "reject_automation")


def _row(r: HubAuditLog, suppliers: dict, pos: dict) -> dict:
    detail = r.detail or {}
    po_number = r.po_number or detail.get("po_number")
    sid = r.supplier_id or detail.get("supplier_id")
    return {"id": r.id, "at": r.at, "actor": r.actor, "actor_type": r.actor_type or "MANAGER", "action": r.action,
            "action_label": ACTION_LABEL.get(r.action, r.action.replace("_", " ")),
            "is_decision": r.action in DECISION_ACTIONS, "ref_type": r.ref_type, "ref_id": r.ref_id,
            "summary": r.summary or f"{ACTION_LABEL.get(r.action, r.action)} ({r.ref_type} #{r.ref_id})",
            "supplier": {"id": sid, "name": suppliers.get(sid)} if sid else None,
            "po_number": po_number, "po_id": pos.get(po_number), "trace_id": r.trace_id, "detail": detail}


def _filtered(actor_type, action, ref_type, supplier_id, po_number, q, since, until, decisions):
    stmt = select(HubAuditLog)
    if actor_type:
        stmt = stmt.where(HubAuditLog.actor_type.in_(actor_type))
    if decisions:
        stmt = stmt.where(HubAuditLog.action.in_(DECISION_ACTIONS))
    if action:
        stmt = stmt.where(HubAuditLog.action.in_(action))
    if ref_type:
        stmt = stmt.where(HubAuditLog.ref_type.in_(ref_type))
    if supplier_id:
        stmt = stmt.where(HubAuditLog.supplier_id == supplier_id)
    if po_number:
        stmt = stmt.where(HubAuditLog.po_number.ilike(f"%{po_number.strip()}%"))
    if since:
        stmt = stmt.where(HubAuditLog.at >= since.replace(tzinfo=None))
    if until:
        stmt = stmt.where(HubAuditLog.at <= until.replace(tzinfo=None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(HubAuditLog.summary.ilike(like), HubAuditLog.actor.ilike(like),
                              HubAuditLog.po_number.ilike(like), cast(HubAuditLog.detail, Text).ilike(like)))
    return stmt


def _lookups(db: Session, rows: list[HubAuditLog]) -> tuple[dict, dict]:
    sids = {r.supplier_id or (r.detail or {}).get("supplier_id") for r in rows} - {None}
    numbers = {r.po_number or (r.detail or {}).get("po_number") for r in rows} - {None}
    suppliers = {i: n for i, n in db.execute(select(Supplier.id, Supplier.name).where(Supplier.id.in_(sids)))} if sids else {}
    pos = {n: i for n, i in db.execute(select(PurchaseOrder.po_number, PurchaseOrder.id)
                                       .where(PurchaseOrder.po_number.in_(numbers)))} if numbers else {}
    return suppliers, pos


@router.get("")
def list_activity(actor_type: list[str] | None = Query(None), action: list[str] | None = Query(None),
                  ref_type: list[str] | None = Query(None), supplier_id: int | None = None, po_number: str | None = None,
                  q: str | None = None, since: datetime | None = None, until: datetime | None = None,
                  decisions: bool = False, before_id: int | None = None, limit: int = Query(100, ge=1, le=500),
                  db: Session = Depends(get_db)):
    """Terbaru dulu. `decisions=true` = hanya keputusan manajer; halaman berikutnya lewat `before_id`."""
    stmt = _filtered(actor_type, action, ref_type, supplier_id, po_number, q, since, until, decisions)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    if before_id:
        stmt = stmt.where(HubAuditLog.id < before_id)
    rows = list(db.scalars(stmt.order_by(HubAuditLog.id.desc()).limit(limit)))
    suppliers, pos = _lookups(db, rows)
    items = [_row(r, suppliers, pos) for r in rows]
    return jsonable_encoder({"total": total, "items": items,
                             "next_before_id": rows[-1].id if len(rows) == limit else None})


@router.get("/facets")
def facets(db: Session = Depends(get_db)):
    """Isi filter: jenis aktor, aksi, dan supplier beserta jumlahnya."""
    def counts(col):
        return [{"value": v, "count": n} for v, n in db.execute(
            select(col, func.count()).where(col.isnot(None)).group_by(col).order_by(func.count().desc()))]
    actions = [{**a, "label": ACTION_LABEL.get(a["value"], a["value"])} for a in counts(HubAuditLog.action)]
    sup = counts(HubAuditLog.supplier_id)
    names = {i: n for i, n in db.execute(select(Supplier.id, Supplier.name)
                                          .where(Supplier.id.in_([s["value"] for s in sup])))} if sup else {}
    return {"actor_types": counts(HubAuditLog.actor_type), "actions": actions,
            "suppliers": [{**s, "label": names.get(s["value"], str(s["value"]))} for s in sup]}


@router.get("/{activity_id}")
def get_activity(activity_id: int, db: Session = Depends(get_db)):
    """Satu baris + panggilan LLM dan tool pada trace yang sama (apa yang dilihat & diputuskan agent)."""
    r = db.get(HubAuditLog, activity_id)
    if r is None:
        raise AppError(404, "Aktivitas tidak ditemukan")
    suppliers, pos = _lookups(db, [r])
    runs, tools = [], []
    if r.trace_id:
        runs = [{"id": x.id, "created_at": x.created_at, "agent": x.agent, "status": x.status, "latency_ms": x.latency_ms,
                 "output": x.output, "error": x.error}
                for x in db.scalars(select(AgentRun).where(AgentRun.trace_id == r.trace_id).order_by(AgentRun.id).limit(50))]
        tools = [{"id": x.id, "created_at": x.created_at, "tool": x.tool, "kind": x.kind, "status": x.status,
                  "latency_ms": x.latency_ms}
                 for x in db.scalars(select(ToolRun).where(ToolRun.trace_id == r.trace_id).order_by(ToolRun.id).limit(50))]
    return jsonable_encoder({**_row(r, suppliers, pos), "agent_runs": runs, "tool_runs": tools})
