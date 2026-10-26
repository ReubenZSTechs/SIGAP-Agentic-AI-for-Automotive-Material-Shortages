"""Jejak keputusan manajer & tindakan agent (tabel `hub_audit_log`, sumber halaman Riwayat Aktivitas).

Modul ini sengaja tanpa dependensi berat sehingga bisa dipakai dari tools / workflow agent tanpa impor siklik.
"""
from sqlalchemy.orm import Session

from app.chatbot.tracing import current_trace_id
from app.models import HubAuditLog

AGENT_ACTOR = "Agent"


def actor_type_of(actor: str) -> str:
    a = (actor or "").strip().lower()
    if a == AGENT_ACTOR.lower() or a.startswith("agent"):
        return "AGENT"
    return "SYSTEM" if a in ("system", "sistem", "worker") else "MANAGER"


def record(db: Session, actor: str, action: str, ref_type: str, ref_id, *, summary: str | None = None,
           supplier_id: int | None = None, po_number: str | None = None, actor_type: str | None = None,
           **detail) -> None:
    """Satu baris jejak; tidak pernah diubah. `trace_id` menautkan ke agent_runs / tool_runs alur yang sama."""
    db.add(HubAuditLog(actor=(actor or "-")[:80], actor_type=actor_type or actor_type_of(actor), action=action[:40],
                       ref_type=ref_type[:24], ref_id=str(ref_id)[:40], summary=(summary or "")[:300] or None,
                       supplier_id=supplier_id, po_number=po_number[:24] if po_number else None,
                       trace_id=current_trace_id(), detail=detail or None))


def agent(db: Session, action: str, ref_type: str, ref_id, summary: str, **kw) -> None:
    record(db, AGENT_ACTOR, action, ref_type, ref_id, summary=summary, actor_type="AGENT", **kw)
