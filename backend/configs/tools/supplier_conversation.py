"""Supplier conversations about a PO (Telegram agent): queue, confirm, decline, versions and confirmation details."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import AppError
from app.models import AutomationAction, PORevision, PurchaseOrder, SupplierConversation
from app.models.enums import ConversationPurpose, ConversationStatus, POStatus
from configs.tools.po_common import _FIELD, CS, OPEN_CONVERSATION, RS, SCS, _iso, now, po_snapshot
from configs.tools.po_execute import _check_snapshot, _get_po, confirmation


def queue_conversation(db: Session, po: PurchaseOrder, purpose: ConversationPurpose, action_id: str | None = None,
                       change_request_id: int | None = None) -> SupplierConversation:
    """Queues a supplier conversation; the dispatcher sends the opening message (one active per supplier).

    Every conversation is tracked by a Hub mission first (`app.hub.po_missions`), so the manager sees the
    outreach in Hub Supplier -> Misi before the supplier is contacted.
    """
    from app.hub.po_missions import ensure_po_mission
    conv = SupplierConversation(po_id=po.id, po_number=po.po_number, po_snapshot=po_snapshot(po),
                                supplier_id=po.supplier_id, purpose=purpose, status=CS.QUEUED,
                                transport=settings.TELEGRAM_MODE, automation_action_id=action_id,
                                change_request_id=change_request_id)
    db.add(conv)
    db.flush()
    ensure_po_mission(db, conv)
    return conv


def ensure_confirm_conversation(db: Session, po: PurchaseOrder, action_id: str | None = None) -> SupplierConversation | None:
    """Queues CONFIRM_ORDER for an ISSUED PO unless one is already open (any path that issues a PO)."""
    if po.status != POStatus.ISSUED:
        return None
    busy = db.scalar(select(SupplierConversation.id).where(SupplierConversation.po_id == po.id,
                                                           SupplierConversation.status.in_(OPEN_CONVERSATION)))
    if busy:
        return None
    confirmation(db, po.id).status = SCS.PENDING
    return queue_conversation(db, po, ConversationPurpose.CONFIRM_ORDER, action_id)


def start_supplier_conversation(db: Session, po: PurchaseOrder, purpose: str) -> SupplierConversation:
    """Manual start from the PO page / API: ask an ISSUED PO's supplier to confirm or to agree to a cancellation."""
    if po.status != POStatus.ISSUED:
        raise AppError(409, f"Hanya PO ISSUED yang dapat dikonfirmasi/dibatalkan via supplier (status {po.status.value})")
    if purpose == ConversationPurpose.CONFIRM_ORDER.value:
        conv = ensure_confirm_conversation(db, po)
        if conv is None:
            raise AppError(409, f"Percakapan untuk {po.po_number} masih berjalan")
        return conv
    return request_po_cancellation(db, {"po": po_snapshot(po)}, None)


def close_conversation(conv: SupplierConversation, status: ConversationStatus, **outcome) -> None:
    conv.status = status
    conv.closed_at = now()
    conv.outcome = {**(conv.outcome or {}), **outcome}


def request_po_cancellation(db: Session, proposal: dict, action_id: str | None) -> SupplierConversation:
    """ISSUED PO: ask the supplier to agree to the cancellation before deleting."""
    po = _get_po(db, proposal["po"]["id"])
    _check_snapshot(po, proposal["po"])
    if po.status != POStatus.ISSUED:
        raise AppError(409, f"PO {po.po_number} tidak lagi ISSUED")
    for other in db.scalars(select(SupplierConversation).where(       # konfirmasi lama tidak relevan lagi
            SupplierConversation.po_id == po.id, SupplierConversation.status.in_(OPEN_CONVERSATION))):
        close_conversation(other, CS.CLOSED, superseded_by="cancellation")
    conf = confirmation(db, po.id)
    previous = conf.status.value
    conf.status = SCS.CANCEL_PENDING
    conv = queue_conversation(db, po, ConversationPurpose.CANCEL_ORDER, action_id)
    conv.outcome = {"previous_confirmation": previous}
    return conv


def record_supplier_confirmation(db: Session, conv: SupplierConversation, promised_date: str | None,
                                 reference: str | None) -> None:
    conf = confirmation(db, conv.po_id)
    conf.status = SCS.CONFIRMED
    conf.confirmed_at = now()
    if reference:
        conf.supplier_reference = reference[:80]
    try:
        conf.promised_delivery_date = date.fromisoformat(promised_date) if promised_date else conf.promised_delivery_date
    except ValueError:
        pass
    close_conversation(conv, CS.CONFIRMED, promised_delivery_date=_iso(conf.promised_delivery_date),
                       supplier_reference=conf.supplier_reference)


def record_supplier_decline(db: Session, conv: SupplierConversation, reason: str) -> None:
    if conv.purpose == ConversationPurpose.CANCEL_ORDER:            # PO tetap berlaku seperti sebelumnya
        previous = (conv.outcome or {}).get("previous_confirmation", SCS.PENDING.value)
        confirmation(db, conv.po_id).status = SCS(previous)
    else:
        confirmation(db, conv.po_id).status = SCS.DECLINED
    close_conversation(conv, CS.DECLINED, reason=reason)


def note_action(db: Session, action_id: str | None, status=None, **info) -> None:
    """Records a supplier-side outcome on the automation action that started it (if any)."""
    action = db.get(AutomationAction, action_id) if action_id else None
    if action is None:
        return
    if status is not None:
        action.status = status
    action.result = {**(action.result or {}), **info}


# ------------------------------------- PO versions -------------------------------------
def revisions(db: Session, po_id: int) -> list[PORevision]:
    return list(db.scalars(select(PORevision).where(PORevision.po_id == po_id).order_by(PORevision.version)))


def _add_revision(db: Session, po: PurchaseOrder, snapshot: dict, changes: list[dict], actor: str | None,
                  change_request_id: int | None = None) -> PORevision:
    existing = revisions(db, po.id)
    for r in existing:
        if r.status != RS.SUPERSEDED:
            r.status = RS.SUPERSEDED
    rev = PORevision(po_id=po.id, po_number=po.po_number, version=(existing[-1].version + 1) if existing else 1,
                     snapshot=snapshot, changes=changes, change_request_id=change_request_id,
                     status=RS.CURRENT, created_by=actor)
    db.add(rev)
    db.flush()
    return rev


def record_initial_revision(db: Session, po: PurchaseOrder, snapshot: dict | None = None) -> PORevision:
    """v1 = the PO as first sent to the supplier (no-op when the PO already has versions)."""
    existing = revisions(db, po.id)
    if existing:
        return existing[-1]
    return _add_revision(db, po, snapshot or po_snapshot(po), [], po.decided_by)


def finalize_po_revision(db: Session, po: PurchaseOrder) -> PORevision:
    """The supplier confirmed without further changes: the latest version becomes FINAL, together with
    the agreed delivery date and supplier reference (shown on the final PDF)."""
    rev = record_initial_revision(db, po)
    conf = confirmation(db, po.id)
    rev.snapshot = {**po_snapshot(po), "promised_delivery_date": _iso(conf.promised_delivery_date),
                    "supplier_reference": conf.supplier_reference}
    rev.status, rev.finalized_at = RS.FINAL, now()
    db.flush()
    return rev


# ------------------------------- confirmation details (required) -------------------------------
CONFIRMATION_FIELDS = {"promised_delivery_date": "the delivery date",
                       "supplier_reference": "your order/reference number"}


def collect_confirmation(conv: SupplierConversation, values: dict, required: list[str]) -> list[str]:
    """Adds the confirmation details given in this message to those collected earlier in the
    conversation; returns the required fields that are still missing (in `required` order)."""
    collected = dict((conv.outcome or {}).get("collected") or {})
    for field in CONFIRMATION_FIELDS:
        value = (values.get(field) or "").strip() if isinstance(values.get(field), str) else values.get(field)
        if value:
            collected[field] = value
    if collected.get("promised_delivery_date"):
        try:
            if date.fromisoformat(collected["promised_delivery_date"]) < date.today():
                collected.pop("promised_delivery_date")          # tanggal lampau: minta ulang
        except ValueError:
            collected.pop("promised_delivery_date")
    conv.outcome = {**(conv.outcome or {}), "collected": collected}
    return [f for f in required if not collected.get(f)]


def update_promised_date(db: Session, po: PurchaseOrder, promised: str) -> list[dict]:
    """A supplier gives a (new) delivery date for a confirmed PO: stored on the confirmation and on the
    FINAL version. Returns the lines whose needed-by date is earlier (the manager is told)."""
    d = date.fromisoformat(promised)
    conf = confirmation(db, po.id)
    conf.promised_delivery_date = d
    conf.note = f"Tanggal kirim diperbarui supplier: {d.isoformat()}"
    final = next((r for r in reversed(revisions(db, po.id)) if r.status == RS.FINAL), None)
    if final is not None:
        final.snapshot = {**final.snapshot, "promised_delivery_date": d.isoformat()}
    db.flush()
    return [{"sku": i.sku, "name": i.name, "needed_by_date": _iso(i.needed_by_date)}
            for i in po.items if i.needed_by_date and i.needed_by_date < d]


def revise_promised_date(db: Session, po: PurchaseOrder, promised: str, actor: str | None,
                         change_request_id: int | None = None) -> PORevision:
    """Accepted new delivery date for a confirmed PO (by the agent within its limits, or by the manager):
    stored on the confirmation and as a new FINAL PO version, so the PO and its PDF show the new date."""
    d = date.fromisoformat(promised)
    conf = confirmation(db, po.id)
    old = _iso(conf.promised_delivery_date)
    conf.promised_delivery_date = d
    conf.note = f"Tanggal kirim diperbarui: {old or '-'} → {d.isoformat()}"
    record_initial_revision(db, po)
    change = {"po_item_id": None, "sku": po.po_number, "name": "", "field": "promised_delivery_date",
              "old": old, "new": d.isoformat()}
    rev = _add_revision(db, po, {**po_snapshot(po), "promised_delivery_date": d.isoformat(),
                                 "supplier_reference": conf.supplier_reference}, [change], actor,
                        change_request_id=change_request_id)
    rev.status, rev.finalized_at = RS.FINAL, now()
    db.flush()
    return rev


def valid_future_date(value) -> str | None:
    """YYYY-MM-DD from an agent field, or None when missing, invalid or in the past."""
    try:
        d = date.fromisoformat(str(value).strip()) if value else None
    except ValueError:
        return None
    return d.isoformat() if d and d >= date.today() else None


def missing_fields_text(po_number: str, missing: list[str]) -> str:
    asks = " and ".join(CONFIRMATION_FIELDS.get(f, f) for f in missing)
    return f"Thank you for confirming {po_number}. Please let us know {asks} so we can finalise the PO."


def split_promised_dates(po: PurchaseOrder, proposed: list[dict]) -> tuple[str | None, list[dict]]:
    """A delivery date from the supplier is always their promise, never a revision of our needed-by date
    (the needed-by date stays the deadline; `agent_limits.check_date` compares the two).

    Returns (latest such date as YYYY-MM-DD or None, the remaining proposed changes).
    """
    promised, rest = None, []
    for pc in proposed or []:
        line = _match_line(po, pc.get("material_ref"))
        if _FIELD.get(pc.get("field")) == "needed_by_date" and line is not None:
            try:
                d = date.fromisoformat(str(pc.get("new_value")).strip()).isoformat()
            except ValueError:
                rest.append(pc)
                continue
            promised = max(promised or d, d)
            continue
        rest.append(pc)
    return promised, rest


def _match_line(po: PurchaseOrder, ref: str):
    ref = (ref or "").strip().lower()
    for it in po.items:
        if it.sku.lower() == ref:
            return it
    hits = [it for it in po.items if ref and (ref in it.name.lower() or it.name.lower() in ref)]
    if len(hits) == 1:
        return hits[0]
    return po.items[0] if len(po.items) == 1 else None
