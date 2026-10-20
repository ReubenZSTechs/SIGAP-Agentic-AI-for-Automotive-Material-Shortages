"""WRITE tools for purchase orders, used by the PO automation and supplier-chat agents.

The LLM never calls these with free parameters: callers pass ids taken from DB records
(automation proposals, conversations, change requests). Business rules live here and in
`po_service` (status machine, stale-run marking); agents only classify and write text.
"""
import re
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import AppError
from app.database import engine
from app.models import (AutomationAction, Material, POChangeRequest, POSupplierConfirmation, PurchaseOrder,
                        Supplier, SupplierConversation)
from app.models.enums import (ChangeRequestStatus, ConversationPurpose, ConversationStatus, ItemCategory,
                              POSource, POStatus, SupplierConfirmationStatus)
from app.services import master_service, po_service
from configs.tools.curated import resolve_materials

CS, CRS, SCS = ConversationStatus, ChangeRequestStatus, SupplierConfirmationStatus
ACTIVE_CONVERSATION = (CS.AWAITING_SUPPLIER, CS.REVISION_REQUESTED)
OPEN_CONVERSATION = (CS.QUEUED, *ACTIVE_CONVERSATION)
EDITABLE = (POStatus.DRAFT, POStatus.REJECTED)
_FIELD = {"qty": "qty_ordered", "unit_price": "unit_price", "needed_by_date": "needed_by_date"}
MAX_OPTIONS = 6


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@contextmanager
def write_session():
    """One atomic unit of work around `po_service` calls.

    `po_service` commits after every step; with `create_savepoint` those commits only release
    savepoints, and the outer transaction commits once at the end (or rolls back entirely).
    """
    with engine.connect() as conn:
        trans = conn.begin()
        db = Session(bind=conn, autoflush=False, join_transaction_mode="create_savepoint")
        try:
            yield db
            db.commit()
            trans.commit()
        except BaseException:
            trans.rollback()
            raise
        finally:
            db.close()


# --------------------------------- snapshots & formatting ---------------------------------
def _iso(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def po_snapshot(po: PurchaseOrder) -> dict:
    """JSON copy of a PO (kept on conversations / change requests, survives a hard delete)."""
    return {
        "id": po.id, "po_number": po.po_number, "status": po.status.value, "source": po.source.value,
        "supplier_id": po.supplier_id, "supplier_code": po.supplier.code, "supplier_name": po.supplier.name,
        "payment_term_days": po.supplier.payment_term_days, "po_date": _iso(po.po_date),
        "total_amount": po.total_amount, "notes": po.notes,
        "items": [{"po_item_id": i.id, "material_id": i.material_id, "sku": i.sku, "name": i.name, "uom": i.uom,
                   "qty_ordered": i.qty_ordered, "qty_received": i.qty_received, "unit_price": i.unit_price,
                   "line_total": i.line_total, "needed_by_date": _iso(i.needed_by_date)} for i in po.items],
    }


def rupiah(n) -> str:
    return "Rp" + f"{round(n or 0):,}".replace(",", ".")


def fmt_qty(q) -> str:
    return str(int(q)) if float(q).is_integer() else f"{q:g}"


def po_summary_text(snap: dict) -> str:
    """Exact, deterministic PO details appended to every Telegram message (never LLM-written)."""
    lines = [f"{snap['po_number']} · {snap['supplier_name']}"]
    for n, it in enumerate(snap["items"], 1):
        need = f" · dibutuhkan {it['needed_by_date']}" if it.get("needed_by_date") else ""
        lines.append(f"{n}. {it['sku']} {it['name']} — {fmt_qty(it['qty_ordered'])} {it['uom']} × "
                     f"{rupiah(it['unit_price'])} = {rupiah(it['line_total'])}{need}")
    lines.append(f"Total: {rupiah(snap['total_amount'])} · Termin: Net {snap.get('payment_term_days', 0)}")
    return "\n".join(lines)


def _unchanged(po: PurchaseOrder, snap: dict) -> bool:
    """True when status, total and every line still match the snapshot (guards stale decisions)."""
    if po.status.value != snap["status"] or po.total_amount != snap["total_amount"]:
        return False
    now_lines = {(i.id, i.qty_ordered, i.unit_price, i.qty_received) for i in po.items}
    then = {(i["po_item_id"], i["qty_ordered"], i["unit_price"], i["qty_received"]) for i in snap["items"]}
    return now_lines == then


def _has_receipts(po: PurchaseOrder) -> bool:
    return any(i.qty_received > 0 for i in po.items)


# ------------------------------------ supplier choice ------------------------------------
def active_links(db: Session, material_id: int) -> list[dict]:
    """`master_service.list_links` rows usable for ordering: active link AND active supplier."""
    active_suppliers = set(db.scalars(select(Supplier.id).where(Supplier.is_active)))
    return [l for l in master_service.list_links(db, material_id)
            if l["is_active"] and l["supplier_id"] in active_suppliers]


def pick_supplier(links: list[dict], qty: float, exclude_supplier_id: int | None = None) -> dict | None:
    """Chooses the supplier link to propose for `qty` units of one material.

    Used for new PO proposals (no supplier named by the user) and for re-sourcing after a
    supplier revision (`exclude_supplier_id` = the current supplier).

    `links`: rows from `active_links()` with keys supplier_id, supplier_code, supplier_name,
    unit_price, lead_time_days, moq, is_preferred, is_cheapest, is_fastest.
    Returns the chosen link, or None when no link is acceptable.
    """
    candidates = [l for l in links if l["supplier_id"] != exclude_supplier_id]
    if not candidates:
        return None
    # Utamakan supplier yang MOQ-nya terpenuhi; bila tidak ada, tetap usulkan (resolver menambah peringatan MOQ).
    within_moq = [l for l in candidates if qty >= l["moq"]] or candidates
    # Preferred dulu (kontrak/kesepakatan pembelian), lalu termurah, lalu tercepat, lalu kode (deterministik).
    return min(within_moq, key=lambda l: (not l["is_preferred"], l["unit_price"], l["lead_time_days"],
                                          l["supplier_code"]))


def _line(link: dict, material: Material | dict, qty: float, needed_by: str | None) -> dict:
    m = material if isinstance(material, dict) else {"material_id": material.id, "sku": material.sku,
                                                       "name": material.name, "uom": material.uom}
    return {**{k: m[k] for k in ("material_id", "sku", "name", "uom")},
            "qty_ordered": qty, "unit_price": link["unit_price"], "line_total": round(qty * link["unit_price"]),
            "lead_time_days": link["lead_time_days"], "moq": link["moq"], "needed_by_date": needed_by}


def _group_by_supplier(db: Session, lines: list[tuple[dict, dict]]) -> list[dict]:
    """[(link, line)] -> one PO proposal per supplier (like `po_service.generate_pos`)."""
    groups: dict[int, list] = defaultdict(list)
    links = {}
    for link, line in lines:
        groups[link["supplier_id"]].append(line)
        links[link["supplier_id"]] = link
    out = []
    for sid, items in groups.items():
        sup = db.get(Supplier, sid)
        out.append({"supplier_id": sid, "supplier_code": sup.code, "supplier_name": sup.name,
                    "payment_term_days": sup.payment_term_days, "items": items,
                    "total_amount": sum(i["line_total"] for i in items)})
    return out


# ---------------------------------- request resolution ----------------------------------
def find_pos(db: Session, ref: str) -> list[PurchaseOrder]:
    """PO by exact number, by numeric id ("123", "PO 123", "#123"), then by partial number."""
    ref = (ref or "").strip()
    if not ref:
        return []
    exact = db.scalars(select(PurchaseOrder).where(func.lower(PurchaseOrder.po_number) == ref.lower())).all()
    if exact:
        return list(exact)
    m = re.fullmatch(r"(?i)(?:po\s*)?(?:id\s*)?#?\s*(\d+)", ref)
    if m:
        po = db.get(PurchaseOrder, int(m.group(1)))
        if po is not None:
            return [po]
    return list(db.scalars(select(PurchaseOrder).where(PurchaseOrder.po_number.ilike(f"%{ref}%"))
                           .order_by(PurchaseOrder.id).limit(MAX_OPTIONS)))


def _find_suppliers(db: Session, term: str) -> list[Supplier]:
    term = term.strip()
    exact = db.scalars(select(Supplier).where(func.lower(Supplier.code) == term.lower(), Supplier.is_active)).all()
    if exact:
        return list(exact)
    return list(db.scalars(select(Supplier).where(Supplier.is_active, (Supplier.code.ilike(f"%{term}%"))
                                                  | (Supplier.name.ilike(f"%{term}%"))).limit(MAX_OPTIONS)))


def _parse_date(value: str | None, field: str, out: dict, not_before: date) -> str | None:
    if not value:
        return None
    try:
        d = date.fromisoformat(value)
    except ValueError:
        out["errors"].append({"field": field, "message": f"'{value}' is not a valid date (YYYY-MM-DD)."})
        return None
    if d < not_before:
        out["errors"].append({"field": field, "message": f"Needed-by date {d} is in the past."})
        return None
    return d.isoformat()


def _resolve_material(db: Session, query: str, field: str, out: dict) -> Material | None:
    mats = [m for m in resolve_materials(db, query, (ItemCategory.PURCHASED,), limit=MAX_OPTIONS) if m.is_active]
    if not mats:
        out["errors"].append({"field": field, "message": f"No purchasable material matches '{query}'."})
        return None
    if len(mats) > 1:
        out["ambiguous"].append({"field": field, "message": f"'{query}' matches several materials.",
                                 "options": [{"label": f"{m.sku} {m.name}", "value": m.sku} for m in mats]})
        return None
    return mats[0]


def _resolve_po_ref(db: Session, draft: dict, out: dict) -> PurchaseOrder | None:
    ref = draft.get("po_reference")
    if not ref:
        out["missing"].append({"field": "po", "message": "Which purchase order (id or PO number)?"})
        return None
    pos = find_pos(db, str(ref))
    if not pos:
        out["errors"].append({"field": "po", "message": f"Purchase order '{ref}' was not found."})
        return None
    if len(pos) > 1:
        out["ambiguous"].append({"field": "po", "message": f"'{ref}' matches several purchase orders.",
                                 "options": [{"label": f"{p.po_number} · {p.supplier_name} · {p.status.value}",
                                              "value": p.po_number} for p in pos]})
        return None
    return pos[0]


def _resolve_create(db: Session, draft: dict, out: dict, today: date) -> None:
    items = draft.get("items") or []
    if not items:
        out["missing"].append({"field": "items", "message": "Which material(s) and how many?"})
        return
    supplier = None
    if draft.get("supplier_query"):
        sups = _find_suppliers(db, draft["supplier_query"])
        if not sups:
            out["errors"].append({"field": "supplier", "message": f"Supplier '{draft['supplier_query']}' was not found."})
        elif len(sups) > 1:
            out["ambiguous"].append({"field": "supplier", "message": "Several suppliers match.",
                                     "options": [{"label": f"{s.code} {s.name}", "value": s.code} for s in sups]})
        else:
            supplier = sups[0]
    needed_by = _parse_date(draft.get("needed_by_date"), "needed_by_date", out, today)
    merged: dict[int, tuple[Material, float]] = {}
    for n, it in enumerate(items):
        m = _resolve_material(db, it.get("material_query") or "", f"items.{n}.material", out)
        qty = it.get("qty")
        if qty is None or qty <= 0:
            what = m.name if m else (it.get("material_query") or "this material")
            out["missing"].append({"field": f"items.{n}.qty", "message": f"How many {what}?"})
            continue
        if m is not None:
            merged[m.id] = (m, merged.get(m.id, (m, 0))[1] + qty)
    lines, warnings = [], []
    for m, qty in merged.values():
        links = active_links(db, m.id)
        if supplier is not None:
            link = next((l for l in links if l["supplier_id"] == supplier.id), None)
            if link is None:
                out["ambiguous"].append({
                    "field": "supplier", "message": f"{supplier.name} does not supply {m.sku} {m.name}.",
                    "options": [{"label": f"{l['supplier_code']} {l['supplier_name']} ({rupiah(l['unit_price'])}, "
                                          f"{l['lead_time_days']} hari)", "value": l["supplier_code"]} for l in links]})
                continue
        else:
            link = pick_supplier(links, qty)
            if link is None:
                out["errors"].append({"field": "supplier", "message": f"No active supplier can deliver {m.sku} {m.name}."})
                continue
        if qty < link["moq"]:
            warnings.append(f"{m.sku}: qty {fmt_qty(qty)} di bawah MOQ {fmt_qty(link['moq'])} {link['supplier_name']}")
        lines.append((link, _line(link, m, qty, needed_by)))
    if lines and not (out["missing"] or out["ambiguous"] or out["errors"]):
        pos = _group_by_supplier(db, lines)
        out["proposal"] = {"operation": "create", "purchase_orders": pos, "notes": draft.get("notes"),
                           "grand_total": sum(p["total_amount"] for p in pos), "warnings": warnings}


def _resolve_update(db: Session, po: PurchaseOrder, draft: dict, out: dict, today: date) -> None:
    if po.source != POSource.MANUAL or po.status not in EDITABLE:
        out["refusal"] = (f"PO {po.po_number} is a {po.source.value} PO with status {po.status.value}. Only MANUAL "
                          "POs in DRAFT or REJECTED can be edited; to change an issued PO, delete it and create a new one.")
        return
    if draft.get("supplier_query"):
        out["errors"].append({"field": "supplier", "message": "Changing the supplier of a PO is not supported; "
                                                             "delete the PO and create a new one."})
    after = {i.material_id: {"material_id": i.material_id, "sku": i.sku, "name": i.name, "uom": i.uom,
                             "qty_ordered": i.qty_ordered, "unit_price": i.unit_price,
                             "needed_by_date": _iso(i.needed_by_date)} for i in po.items}
    changed = False
    for n, it in enumerate(draft.get("items") or []):
        m = _resolve_material(db, it.get("material_query") or "", f"items.{n}.material", out)
        qty = it.get("qty")
        if qty is None or qty <= 0:
            out["missing"].append({"field": f"items.{n}.qty", "message": f"New quantity for {m.name if m else 'this material'}?"})
            continue
        if m is None:
            continue
        if m.id in after:
            after[m.id]["qty_ordered"] = qty
        else:
            link = next((l for l in active_links(db, m.id) if l["supplier_id"] == po.supplier_id), None)
            if link is None:
                out["errors"].append({"field": f"items.{n}.material",
                                      "message": f"{po.supplier_name} does not supply {m.sku} {m.name}."})
                continue
            after[m.id] = {"material_id": m.id, "sku": m.sku, "name": m.name, "uom": m.uom, "qty_ordered": qty,
                           "unit_price": link["unit_price"], "needed_by_date": None}
        changed = True
    needed_by = _parse_date(draft.get("needed_by_date"), "needed_by_date", out, max(today, po.po_date))
    if needed_by:
        for line in after.values():
            line["needed_by_date"] = needed_by
        changed = True
    if draft.get("notes"):
        changed = True
    if not changed and not (out["missing"] or out["errors"] or out["ambiguous"]):
        out["missing"].append({"field": "changes", "message": f"What should be changed on {po.po_number}?"})
    if changed and not (out["missing"] or out["ambiguous"] or out["errors"]):
        items = [{**l, "line_total": round(l["qty_ordered"] * l["unit_price"])} for l in after.values()]
        out["proposal"] = {"operation": "update", "po": po_snapshot(po), "items_after": items,
                           "notes": draft.get("notes"), "total_before": po.total_amount,
                           "total_after": sum(i["line_total"] for i in items)}


def _resolve_delete(db: Session, po: PurchaseOrder, out: dict) -> None:
    if po.status in po_service.NOT_DELETABLE or _has_receipts(po):
        out["refusal"] = (f"PO {po.po_number} has already received goods ({po.status.value}); it cannot be deleted. "
                          "Received stock needs a return process instead.")
        return
    busy = db.scalar(select(SupplierConversation.id).where(
        SupplierConversation.po_id == po.id, SupplierConversation.purpose == ConversationPurpose.CANCEL_ORDER,
        SupplierConversation.status.in_(OPEN_CONVERSATION)))
    if busy:
        out["refusal"] = f"A cancellation request for PO {po.po_number} is already in progress with the supplier."
        return
    mode = "supplier_cancellation" if po.status == POStatus.ISSUED else "immediate"
    out["proposal"] = {"operation": "delete", "po": po_snapshot(po), "mode": mode}


def resolve_po_request(db: Session, draft: dict, today: date | None = None) -> dict:
    """Matches a parsed request against the DB. Read-only.

    Returns {status: resolved|needs_input|refused, operation, missing[], ambiguous[], errors[],
    refusal, proposal}. `proposal` holds only DB-derived values (prices from MaterialSupplier).
    """
    today = today or date.today()
    op = draft.get("operation")
    out = {"operation": op, "missing": [], "ambiguous": [], "errors": [], "refusal": None, "proposal": None}
    if op == "create":
        _resolve_create(db, draft, out, today)
    elif op in ("update", "delete"):
        po = _resolve_po_ref(db, draft, out)
        if po is not None:
            (_resolve_update(db, po, draft, out, today) if op == "update" else _resolve_delete(db, po, out))
    else:
        out["missing"].append({"field": "operation", "message": "Create, change or delete a purchase order?"})
    if out["refusal"]:
        out["status"] = "refused"
    elif out["proposal"] is not None:
        out["status"] = "resolved"
    else:
        out["status"] = "needs_input"
    return out


# ------------------------------------ write actions ------------------------------------
def confirmation(db: Session, po_id: int) -> POSupplierConfirmation:
    conf = db.scalar(select(POSupplierConfirmation).where(POSupplierConfirmation.po_id == po_id))
    if conf is None:
        conf = POSupplierConfirmation(po_id=po_id, status=SCS.PENDING)
        db.add(conf)
        db.flush()
    return conf


def _get_po(db: Session, po_id: int | None) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id) if po_id else None
    if po is None:
        raise AppError(404, "Purchase Order tidak ditemukan (mungkin sudah dihapus)")
    return po


def _check_snapshot(po: PurchaseOrder, snap: dict) -> None:
    if not _unchanged(po, snap):
        raise AppError(409, f"PO {po.po_number} berubah sejak usulan dibuat; ulangi permintaan")


def create_and_issue_po(db: Session, group: dict, actor: str, notes: str | None = None) -> PurchaseOrder:
    """Manual PO -> submit -> approve (by `actor`) -> ISSUED, via the regular status machine."""
    data = {"supplier_id": group["supplier_id"], "po_date": date.today(), "notes": notes,
            "items": [{"material_id": i["material_id"], "qty_ordered": i["qty_ordered"], "unit_price": i["unit_price"],
                       "needed_by_date": date.fromisoformat(i["needed_by_date"]) if i.get("needed_by_date") else None}
                      for i in group["items"]]}
    po = po_service.create_manual(db, data)
    po_service.submit(db, po)
    po_service.approve(db, po, actor)
    po_service.change_status(db, po, POStatus.ISSUED)
    confirmation(db, po.id).status = SCS.PENDING
    db.flush()
    return po


def update_draft_po(db: Session, proposal: dict) -> PurchaseOrder:
    po = _get_po(db, proposal["po"]["id"])
    _check_snapshot(po, proposal["po"])
    data = {"items": [{"material_id": i["material_id"], "qty_ordered": i["qty_ordered"], "unit_price": i["unit_price"],
                       "needed_by_date": date.fromisoformat(i["needed_by_date"]) if i.get("needed_by_date") else None}
                      for i in proposal["items_after"]]}
    if proposal.get("notes"):
        data["notes"] = proposal["notes"][:500]
    return po_service.update_manual(db, po, data)


def delete_po(db: Session, po_id: int, snapshot: dict | None = None) -> dict:
    """Hard delete with stock revert (see `po_service.delete_po`); returns the PO snapshot."""
    po = _get_po(db, po_id)
    if snapshot is not None:
        _check_snapshot(po, snapshot)
    snap = po_snapshot(po)
    po_service.delete_po(db, po)
    return snap


def queue_conversation(db: Session, po: PurchaseOrder, purpose: ConversationPurpose, action_id: str | None = None,
                       change_request_id: int | None = None) -> SupplierConversation:
    """Queues a supplier conversation; the dispatcher sends the opening message (one active per supplier)."""
    conv = SupplierConversation(po_id=po.id, po_number=po.po_number, po_snapshot=po_snapshot(po),
                                supplier_id=po.supplier_id, purpose=purpose, status=CS.QUEUED,
                                transport=settings.TELEGRAM_MODE, automation_action_id=action_id,
                                change_request_id=change_request_id)
    db.add(conv)
    db.flush()
    return conv


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


# ---------------------------------- supplier revisions ----------------------------------
def _match_line(po: PurchaseOrder, ref: str):
    ref = (ref or "").strip().lower()
    for it in po.items:
        if it.sku.lower() == ref:
            return it
    hits = [it for it in po.items if ref and (ref in it.name.lower() or it.name.lower() in ref)]
    if len(hits) == 1:
        return hits[0]
    return po.items[0] if len(po.items) == 1 else None


def _parse_change(field: str, raw: str, po: PurchaseOrder):
    raw = str(raw).strip()
    if field == "qty_ordered":
        value = float(raw.replace(",", "."))
        if value <= 0:
            raise ValueError("qty must be > 0")
        return value
    if field == "unit_price":
        digits = re.sub(r"\D", "", raw.split(",")[0])
        if not digits:
            raise ValueError("price is not a number")
        return int(digits)
    value = date.fromisoformat(raw)
    if value < po.po_date:
        raise ValueError("date is before the PO date")
    return value.isoformat()


def find_alternative_suppliers(db: Session, po: PurchaseOrder) -> list[dict] | None:
    """Other suppliers for every open line (via `pick_supplier`), grouped per supplier; None if any line has none."""
    lines = []
    for it in po.items:
        qty = it.qty_ordered - it.qty_received
        link = pick_supplier(active_links(db, it.material_id), qty, exclude_supplier_id=po.supplier_id)
        if link is None:
            return None
        lines.append((link, _line(link, {"material_id": it.material_id, "sku": it.sku, "name": it.name, "uom": it.uom},
                                  qty, _iso(it.needed_by_date))))
    return _group_by_supplier(db, lines) if lines else None


def open_change_request(db: Session, conv: SupplierConversation, proposed: list[dict], supplier_message: str,
                        max_revision_rounds: int) -> POChangeRequest | None:
    """Validates a supplier's revision and stores it with the options the manager may choose.

    Options are computed here, never by the LLM: abort (always), approve_change (every change
    valid, PO still ISSUED without receipts, revision rounds left), resource (alternatives exist).
    Returns None when the supplier proposed nothing concrete.
    """
    if not proposed:
        return None
    po = _get_po(db, conv.po_id)
    valid, invalid = [], []
    for pc in proposed:
        line, field = _match_line(po, pc.get("material_ref")), _FIELD.get(pc.get("field"))
        if line is None or field is None:
            invalid.append({**pc, "error": "not a line of this PO"})
            continue
        try:
            new = _parse_change(field, pc.get("new_value"), po)
        except ValueError as e:
            invalid.append({**pc, "error": str(e)})
            continue
        old = _iso(getattr(line, field))
        if new != old:
            valid.append({"po_item_id": line.id, "sku": line.sku, "name": line.name, "uom": line.uom,
                          "field": field, "old": old, "new": new, "reason": pc.get("reason")})
    conf = confirmation(db, po.id)
    snap = po_snapshot(po)
    options = [{"key": "abort", "label": "Batalkan PO",
                "effect": f"{po.po_number} dihapus (stok on-order dikembalikan) dan supplier diberi tahu."}]
    if valid and not invalid and po.status == POStatus.ISSUED and not _has_receipts(po) \
            and conf.revision_round < max_revision_rounds:
        changes = {(c["po_item_id"], c["field"]): c["new"] for c in valid}
        after = []
        for it in snap["items"]:
            line = {**it, **{f: changes[(it["po_item_id"], f)] for f in _FIELD.values() if (it["po_item_id"], f) in changes}}
            line["line_total"] = round(line["qty_ordered"] * line["unit_price"])
            after.append(line)
        options.append({"key": "approve_change", "label": "Setujui perubahan",
                        "effect": f"{po.po_number} direvisi lalu dikirim ulang ke supplier untuk konfirmasi.",
                        "items_after": after, "total_before": po.total_amount,
                        "total_after": sum(i["line_total"] for i in after)})
    alternatives = find_alternative_suppliers(db, po)
    if alternatives:
        names = ", ".join(g["supplier_name"] for g in alternatives)
        options.append({"key": "resource", "label": "Pesan ke supplier lain",
                        "effect": f"PO baru diterbitkan ke {names}; {po.po_number} dihapus dan supplier lama diberi tahu.",
                        "purchase_orders": alternatives,
                        "grand_total": sum(g["total_amount"] for g in alternatives)})
    cr = POChangeRequest(po_id=po.id, po_number=po.po_number, po_snapshot=snap, conversation_id=conv.id,
                         supplier_id=po.supplier_id, proposed_changes=valid, invalid_changes=invalid,
                         supplier_message=supplier_message, options=options, status=CRS.PENDING_MANAGER)
    db.add(cr)
    db.flush()
    conf.status = SCS.REVISION_PENDING
    conv.status = CS.REVISION_REQUESTED
    conv.outcome = {**(conv.outcome or {}), "change_request_id": cr.id}
    return cr


def apply_change_request(db: Session, cr: POChangeRequest, choice: str, actor: str) -> dict:
    """Executes the manager's choice. Returns ids of new POs / queued conversations and supplier notices.

    Outbound Telegram messages are NOT sent here; the caller sends them after the commit.
    """
    if cr.status not in (CRS.PENDING_MANAGER, CRS.AWAITING_MANAGER_CONFIRM):
        raise AppError(409, f"Permintaan revisi #{cr.id} sudah diproses ({cr.status.value})")
    option = next((o for o in cr.options if o["key"] == choice), None)
    if option is None:
        raise AppError(422, f"Opsi '{choice}' tidak tersedia untuk permintaan revisi #{cr.id}")
    po = _get_po(db, cr.po_id)
    _check_snapshot(po, cr.po_snapshot)
    conv = db.get(SupplierConversation, cr.conversation_id) if cr.conversation_id else None
    action_id = conv.automation_action_id if conv else None
    result = {"choice": choice, "po_number": po.po_number, "new_pos": [], "queued_conversations": [], "notices": []}

    if choice == "approve_change":
        po_service.apply_supplier_revision(db, po, [{"po_item_id": c["po_item_id"], "field": c["field"],
                                                     "new": c["new"]} for c in cr.proposed_changes])
        conf = confirmation(db, po.id)
        conf.revision_round += 1
        conf.status = SCS.PENDING
        if conv:
            close_conversation(conv, CS.CLOSED, change_request_id=cr.id, result="change_approved")
        new_conv = queue_conversation(db, po, ConversationPurpose.REVISION_CONFIRM, action_id, change_request_id=cr.id)
        result["queued_conversations"].append(new_conv.id)
        result["total_after"] = po.total_amount
        cr.status = CRS.CHANGE_APPROVED
    elif choice == "abort":
        if conv:
            close_conversation(conv, CS.CLOSED, change_request_id=cr.id, result="aborted")
        snap = delete_po(db, po.id)
        result["notices"].append({"supplier_id": cr.supplier_id, "conversation_id": cr.conversation_id, "snapshot": snap})
        note_action(db, action_id, supplier_outcome=f"{snap['po_number']} dibatalkan manajer setelah permintaan revisi")
        cr.status = CRS.ABORTED
    else:   # resource: terbitkan PO pengganti DULU, baru hapus PO lama
        for group in option["purchase_orders"]:
            new = create_and_issue_po(db, group, actor, notes=f"Pengganti {po.po_number} (revisi supplier tidak diterima)")
            new_conv = queue_conversation(db, new, ConversationPurpose.CONFIRM_ORDER, action_id)
            result["new_pos"].append({"id": new.id, "po_number": new.po_number, "supplier_name": new.supplier_name,
                                      "total_amount": new.total_amount})
            result["queued_conversations"].append(new_conv.id)
        if conv:
            close_conversation(conv, CS.CLOSED, change_request_id=cr.id, result="resourced")
        snap = delete_po(db, po.id)
        result["notices"].append({"supplier_id": cr.supplier_id, "conversation_id": cr.conversation_id, "snapshot": snap})
        note_action(db, action_id, supplier_outcome=f"{snap['po_number']} dialihkan ke "
                                                    + ", ".join(p["po_number"] for p in result["new_pos"]))
        cr.status = CRS.RESOURCED
    cr.manager_choice, cr.pending_choice, cr.decided_at = choice, None, now()
    cr.result = {k: v for k, v in result.items() if k != "notices"}
    db.flush()
    return result


WRITE_TOOLS = {
    "create_and_issue_po": create_and_issue_po,
    "update_draft_po": update_draft_po,
    "delete_po": delete_po,
    "request_po_cancellation": request_po_cancellation,
    "queue_conversation": queue_conversation,
    "record_supplier_confirmation": record_supplier_confirmation,
    "record_supplier_decline": record_supplier_decline,
    "open_change_request": open_change_request,
    "apply_change_request": apply_change_request,
}
