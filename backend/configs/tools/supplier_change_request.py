"""Supplier requests that change a PO: validate, decide within the agent's limits, or offer the manager options.

Kinds of `POChangeRequest` (options are always computed here, never by the LLM):

    REVISION      qty (and/or price) changes            abort | approve_change | resource
    PRICE_CHANGE  unit price outside the ±tolerance band approve_change | negotiate | resource | abort
    DATE_CHANGE   delivery date outside the day window  accept_date | reject_date | resource | abort
    CANCELLATION  PO cancelled (by the supplier, or by  resource | continue_project | cancel_project
                  the agent for a nonsensical price); the replacement is late / off-band / missing

Within the limits (`agent_limits`), the agent applies the change itself and only informs the manager. A price
change beyond the auto-cancel limit (or a price <= 0) cancels the PO without a human and re-sources it.
All texts here end up in Telegram messages and are English.
"""
import re
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import POChangeRequest, PurchaseOrder, Schedule, SupplierConversation
from app.models.enums import ConversationPurpose, POStatus, ScheduleStatus
from app.services import bom_service, planning_service, po_service, schedule_service
from configs.tools import agent_limits as L
from configs.tools.po_common import _FIELD, CRS, CS, OPEN_CONVERSATION, SCS, _has_receipts, _iso, now, po_snapshot, rupiah
from configs.tools.po_execute import _check_snapshot, _get_po, cancel_po, confirmation, create_and_issue_po
from configs.tools.po_sourcing import _group_by_supplier, _line, active_links, pick_replacement, pick_supplier
from configs.tools.supplier_conversation import (
    _add_revision,
    _match_line,
    close_conversation,
    finalize_po_revision,
    note_action,
    queue_conversation,
    record_supplier_confirmation,
    revise_promised_date,
    revisions,
)

AGENT = "Agent"
FULFILLABLE = (POStatus.ISSUED, POStatus.PARTIALLY_RECEIVED)
OPTION_LABEL = {
    "abort": "Cancel PO", "approve_change": "Approve change", "resource": "Order from another supplier",
    "negotiate": "Offer a counter price", "accept_date": "Accept new date", "reject_date": "Reject new date",
    "continue_project": "Continue project", "cancel_project": "Cancel project",
}


# ---------------------------------- supplier revisions ----------------------------------

def parse_rupiah(raw: str) -> int:
    """Supplier-written Rupiah amount -> integer Rupiah; raises ValueError when it is not a price.

    Examples the agent may pass on: "12500", "12.500", "Rp 12.500,00", "12500.00", "12,500".
    """
    s = re.sub(r"(?i)^\s*rp\.?|\s", "", str(raw))
    if not re.fullmatch(r"\d[\d.,]*", s) or s[-1] in ".,":
        raise ValueError("price is not a number")
    # Separator terakhir diikuti tepat dua digit = sen ("12.500,00", "12500.00"); separator lain = ribuan
    # ("12.500", "12,500", "1.250.000"). Rupiah dibulatkan ke rupiah penuh.
    whole, cents = s, "0"
    m = re.fullmatch(r"(.*\d)[.,](\d{2})", s)
    if m:
        whole, cents = m.groups()
    return int(re.sub(r"[.,]", "", whole)) + (1 if int(cents) >= 50 else 0)


def _parse_change(field: str, raw: str, po: PurchaseOrder):
    raw = str(raw).strip()
    if field == "qty_ordered":
        value = float(raw.replace(",", "."))
        if value <= 0:
            raise ValueError("qty must be > 0")
        return value
    if field == "unit_price":
        return parse_rupiah(raw)
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


def _resource_option(groups: list[dict], effect: str, warnings: list[str] | None = None) -> dict:
    return {"key": "resource", "label": OPTION_LABEL["resource"], "effect": effect, "purchase_orders": groups,
            "grand_total": sum(g["total_amount"] for g in groups), "warnings": warnings or []}


def _abort_option(po_number: str) -> dict:
    return {"key": "abort", "label": OPTION_LABEL["abort"],
            "effect": f"{po_number} is cancelled (status Cancelled, PO data kept; on-order stock released) "
                      "and the supplier is informed."}


def _validate_changes(po: PurchaseOrder, proposed: list[dict]) -> tuple[list[dict], list[dict]]:
    """Supplier-proposed line changes -> (valid changes with old/new values, invalid ones with an error)."""
    valid, invalid = [], []
    for pc in proposed or []:
        line, field = _match_line(po, pc.get("material_ref")), _FIELD.get(pc.get("field"))
        if line is None or field is None or field == "needed_by_date":
            invalid.append({**pc, "error": "not a line of this PO" if line is None or field is None
                            else "delivery dates are handled as a promised date"})
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
    return valid, invalid


def unreasonable_prices(db: Session, po: PurchaseOrder, proposed: list[dict]) -> list[dict]:
    """Unit-price changes beyond the auto-cancel limit (or <= 0): [{sku, name, old, new, pct}] (empty = none)."""
    valid, _ = _validate_changes(po, proposed)
    lim = L.limits(db)
    out = []
    for c in valid:
        if c["field"] != "unit_price":
            continue
        chk = L.check_price(db, c["old"], c["new"], lim)
        if chk.verdict == L.CANCEL:
            out.append({"sku": c["sku"], "name": c["name"], "old": c["old"], "new": c["new"], "pct": round(chk.pct, 1),
                        "cancel_at": chk.cancel_at})
    return out


def open_change_request(db: Session, conv: SupplierConversation, proposed: list[dict], supplier_message: str,
                        max_revision_rounds: int) -> POChangeRequest | None:
    """Validates a supplier's revision (qty / unit price) and decides who handles it.

    - Only price changes, each within the ±`price_tolerance_pct` band (up OR down): the agent approves and
      revises the PO itself (`cr.result["auto"]`; the caller informs the manager instead of asking).
    - Only price changes, at least one outside the band: PRICE_CHANGE with approve / negotiate / cheaper
      supplier / cancel. (Changes beyond the auto-cancel limit are handled before this by
      `cancel_for_unreasonable_price`; they only land here when the PO cannot be cancelled.)
    - Anything with qty (or invalid) changes: REVISION (abort | approve_change | resource).
    Returns None when the supplier proposed nothing concrete.
    """
    if not proposed:
        return None
    po = _get_po(db, conv.po_id)
    valid, invalid = _validate_changes(po, proposed)
    if not valid and not invalid:
        return None
    conf = confirmation(db, po.id)
    snap = po_snapshot(po)
    can_approve = bool(valid) and not invalid and po.status == POStatus.ISSUED and not _has_receipts(po) \
        and conf.revision_round < max_revision_rounds
    price_only = can_approve and all(c["field"] == "unit_price" for c in valid)
    lim = L.limits(db)
    within = price_only and all(L.check_price(db, c["old"], c["new"], lim).verdict == L.AUTO for c in valid)
    kind = "PRICE_CHANGE" if price_only and not within else "REVISION"

    options = [_abort_option(po.po_number)]
    if can_approve:
        after = _items_after(snap, {(c["po_item_id"], c["field"]): c["new"] for c in valid})
        options.append({"key": "approve_change",
                        "label": "Accept new price" if kind == "PRICE_CHANGE" else OPTION_LABEL["approve_change"],
                        "effect": f"{po.po_number} is revised; the supplier receives the list of changes to confirm.",
                        "items_after": after, "total_before": po.total_amount,
                        "total_after": sum(i["line_total"] for i in after)})
    if kind == "PRICE_CHANGE":
        options.append({"key": "negotiate", "label": OPTION_LABEL["negotiate"], "needs": "counter_prices",
                        "effect": "The agent sends your counter price to the supplier as a revision; the "
                                  "supplier confirms it or proposes again.",
                        "lines": [{"po_item_id": c["po_item_id"], "sku": c["sku"], "name": c["name"],
                                   "old": c["old"], "asked": c["new"]} for c in valid]})
    alternatives = find_alternative_suppliers(db, po)
    if alternatives:
        cheaper = kind != "PRICE_CHANGE" or sum(g["total_amount"] for g in alternatives) < \
            next(o["total_after"] for o in options if o["key"] == "approve_change")
        if cheaper:
            names = ", ".join(g["supplier_name"] for g in alternatives)
            label_effect = (f"A new PO is issued to {names}; {po.po_number} is cancelled (kept on record) and "
                            "the current supplier is informed.")
            opt = _resource_option(alternatives, label_effect)
            if kind == "PRICE_CHANGE":
                opt["label"] = "Find a cheaper supplier"
            options.append(opt)
    cr = POChangeRequest(kind=kind, po_id=po.id, po_number=po.po_number, po_snapshot=snap, conversation_id=conv.id,
                         supplier_id=po.supplier_id, proposed_changes=valid, invalid_changes=invalid,
                         supplier_message=supplier_message, options=options, status=CRS.PENDING_MANAGER)
    db.add(cr)
    db.flush()
    conf.status = SCS.REVISION_PENDING
    conv.status = CS.REVISION_REQUESTED
    conv.outcome = {**(conv.outcome or {}), "change_request_id": cr.id}
    if within:                                                    # inside the ±band: the agent approves itself
        result = apply_change_request(db, cr, "approve_change", AGENT)
        cr.result = {**(cr.result or {}), "auto": True}
        cr.result["queued_conversations"] = result["queued_conversations"]
    return cr


def _items_after(snap: dict, changes: dict) -> list[dict]:
    after = []
    for it in snap["items"]:
        line = {**it, **{f: changes[(it["po_item_id"], f)] for f in _FIELD.values() if (it["po_item_id"], f) in changes}}
        line["line_total"] = round(line["qty_ordered"] * line["unit_price"])
        after.append(line)
    return after


# ------------------------------------- delivery dates -------------------------------------
def _replacement_groups(db: Session, items: list[dict], exclude_supplier_id: int, old_prices: dict | None = None):
    """Replacement supplier per open line (`pick_replacement`, deadline-aware) grouped per supplier.

    A replacement price counts as acceptable only inside the ±price band around the original price (both ways).
    Returns (groups | None when a line has no supplier, warnings, all_on_time, all_price_ok).
    """
    lim = L.limits(db)
    late_days = int(lim["delivery_late_days"])
    lines, warnings, on_time, price_ok = [], [], True, True
    today = date.today()
    for it in items:
        qty = it["qty_ordered"] - it.get("qty_received", 0)
        if qty <= 0:
            continue
        needed = date.fromisoformat(it["needed_by_date"]) if it.get("needed_by_date") else None
        limit = needed + timedelta(days=late_days) if needed else None
        link, in_time = pick_replacement(active_links(db, it["material_id"]), qty, limit, exclude_supplier_id, today)
        if link is None:
            return None, [f"{it['sku']} {it['name']}: no other active supplier"], False, False
        if not in_time:
            on_time = False
            arrival = today + timedelta(days=link["lead_time_days"])
            warnings.append(f"{it['name']}: {link['supplier_name']} arrives {arrival.isoformat()} at the earliest "
                            f"(deadline {it['needed_by_date']})")
        old = (old_prices or {}).get(it["material_id"], it.get("unit_price"))
        chk = L.check_price(db, old, link["unit_price"], lim) if old is not None else None
        if chk is not None and chk.verdict != L.AUTO:
            price_ok = False
            warnings.append(f"{it['name']}: {link['supplier_name']} {rupiah(link['unit_price'])} vs {rupiah(old)} "
                            f"({chk.pct:+.1f}%, outside ±{chk.tolerance:g}%)")
        lines.append((link, _line(link, {k: it[k] for k in ("material_id", "sku", "name", "uom")}, qty,
                                  it.get("needed_by_date"))))
    return (_group_by_supplier(db, lines) if lines else []), warnings, on_time, price_ok


def open_date_change(db: Session, po: PurchaseOrder, check: L.DateCheck, supplier_message: str,
                     conv: SupplierConversation | None = None) -> POChangeRequest:
    """Delivery date outside the agent's window -> manager decides (accept / reject / other supplier / cancel)."""
    conf = confirmation(db, po.id)
    old = _iso(conf.promised_delivery_date)
    change = {"po_item_id": None, "sku": po.po_number, "name": "", "uom": None, "field": "promised_delivery_date",
              "old": old, "new": check.new_date.isoformat(), "deadline": _iso(check.deadline),
              "delta_days": check.delta_days, "reason": check.describe()}
    options = [{"key": "accept_date", "label": OPTION_LABEL["accept_date"],
                "effect": f"The delivery date of {po.po_number} becomes {check.new_date.isoformat()}; the PO is "
                          "revised (new version) and the supplier receives a confirmation."},
               {"key": "reject_date", "label": OPTION_LABEL["reject_date"],
                "effect": "The supplier is told the date cannot be accepted"
                          + (f" and asked to deliver by {_iso(check.deadline)}." if check.deadline else ".")}]
    groups, warnings, _, _ = _replacement_groups(db, po_snapshot(po)["items"], po.supplier_id)
    if groups:
        names = ", ".join(g["supplier_name"] for g in groups)
        options.append(_resource_option(groups, f"A new PO is issued to {names}; {po.po_number} is cancelled and "
                                                "the current supplier is informed.", warnings))
    if po.status == POStatus.ISSUED and not _has_receipts(po):
        options.append(_abort_option(po.po_number))
    cr = POChangeRequest(kind="DATE_CHANGE", po_id=po.id, po_number=po.po_number, po_snapshot=po_snapshot(po),
                         conversation_id=conv.id if conv else None, supplier_id=po.supplier_id,
                         proposed_changes=[change], invalid_changes=[], supplier_message=supplier_message,
                         options=options, status=CRS.PENDING_MANAGER)
    db.add(cr)
    db.flush()
    if conv is not None:
        conv.status = CS.REVISION_REQUESTED
        conv.outcome = {**(conv.outcome or {}), "change_request_id": cr.id}
        conf.status = SCS.REVISION_PENDING
    return cr


def apply_delivery_date(db: Session, po: PurchaseOrder, new_date: str, supplier_message: str,
                        actor: str = AGENT) -> dict:
    """A supplier gives a new delivery date for an already confirmed PO (no conversation open).

    Inside the window: recorded on the confirmation + a new FINAL PO version (agent decides).
    Outside: a DATE_CHANGE request for the manager. Returns {auto, check, revision_id?, change_request_id?}.
    """
    check = L.check_date(db, po, date.fromisoformat(new_date))
    if check.ok:
        rev = revise_promised_date(db, po, new_date, actor)
        return {"auto": True, "check": check, "revision_id": rev.id, "version": rev.version}
    cr = open_date_change(db, po, check, supplier_message)
    return {"auto": False, "check": check, "change_request_id": cr.id}


# --------------------------------------- cancellation ---------------------------------------
def affected_schedules(db: Session, material_ids: set[int], until: date | None) -> list[dict]:
    """PLANNED production from today (up to `until`, the latest needed-by) that consumes these materials."""
    q = select(Schedule).where(Schedule.status == ScheduleStatus.PLANNED, Schedule.production_date >= date.today())
    if until is not None:
        q = q.where(Schedule.production_date <= until)
    out, graph = [], None
    for s in db.scalars(q.order_by(Schedule.production_date, Schedule.id)):
        graph = graph or bom_service._load_graph(db)
        try:
            used = set(bom_service.explode(db, s.product_id, s.target_qty, graph=graph))
        except AppError:                                  # BOM belum lengkap: tidak bisa dipastikan, lewati
            continue
        if material_ids & used:
            out.append({"id": s.id, "batch_code": s.batch_code, "product": s.product_name, "qty": s.target_qty,
                        "production_date": s.production_date.isoformat()})
    return out


def handle_supplier_cancellation(db: Session, po: PurchaseOrder, reason: str, supplier_message: str,
                                 actor: str = AGENT) -> dict:
    """The supplier cancels an issued PO: cancel it, then find a replacement within the agent's limits.

    Returns {status: partial | replaced | needs_manager, cancelled, new_pos, queued_conversations,
    change_request_id, warnings}. Outbound messages are sent by the caller after the commit.
    """
    if po.status not in FULFILLABLE:
        raise AppError(409, f"{po.po_number} is {po.status.value}; nothing to cancel")
    if _has_receipts(po):
        return {"status": "partial", "cancelled": None}
    return _cancel_and_resource(db, po, f"cancelled by supplier: {reason}", reason, supplier_message, actor,
                                closed_reason="supplier_cancelled")


def cancel_for_unreasonable_price(db: Session, po: PurchaseOrder, prices: list[dict], supplier_message: str,
                                  actor: str = AGENT) -> dict | None:
    """A price change so far off that it makes no sense (beyond ±`price_cancel_pct`, or <= 0): the agent cancels the
    PO without a human and re-sources it like a supplier cancellation. None when the PO cannot be cancelled
    (goods already received) -> the caller lets the manager decide instead."""
    if po.status not in FULFILLABLE or _has_receipts(po):
        return None
    detail = "; ".join(f"{p['sku']} {rupiah(p['old'])} -> {rupiah(p['new'])} ({p['pct']:+.1f}%)" for p in prices)
    reason = f"price change beyond ±{prices[0]['cancel_at']:g}% ({detail})"
    result = _cancel_and_resource(db, po, f"cancelled by agent: {reason}", reason, supplier_message, actor,
                                  closed_reason="price_unreasonable")
    result["prices"] = prices
    result["reason"] = reason
    return result


def _cancel_and_resource(db: Session, po: PurchaseOrder, cancel_note: str, reason: str, supplier_message: str,
                         actor: str, closed_reason: str) -> dict:
    """Cancel an issued PO (no receipts), then order a replacement within the agent's limits, or ask the manager."""
    for conv in db.scalars(select(SupplierConversation).where(SupplierConversation.po_id == po.id,
                                                              SupplierConversation.status.in_(OPEN_CONVERSATION))):
        close_conversation(conv, CS.CLOSED, reason=closed_reason)
        note_action(db, conv.automation_action_id, supplier_outcome=f"{po.po_number} cancelled ({closed_reason})")
    before = po_snapshot(po)
    conf = confirmation(db, po.id)
    conf.status, conf.note = SCS.DECLINED, cancel_note[:300]
    snap = cancel_po(db, po.id, cancel_note[:200])
    snap["status"] = POStatus.CANCELLED.value
    result = {"status": "needs_manager", "cancelled": before["po_number"], "new_pos": [], "queued_conversations": [],
              "change_request_id": None, "warnings": []}
    old_prices = {i["material_id"]: i["unit_price"] for i in before["items"]}
    groups, warnings, on_time, price_ok = _replacement_groups(db, before["items"], before["supplier_id"], old_prices)
    result["warnings"] = warnings
    if groups and on_time and price_ok:                           # within the limits: the agent orders itself
        for g in groups:
            new = create_and_issue_po(db, g, actor, notes=f"Replacement for {before['po_number']} ({closed_reason})")
            conv = queue_conversation(db, new, ConversationPurpose.CONFIRM_ORDER)
            result["new_pos"].append({"id": new.id, "po_number": new.po_number, "supplier_name": new.supplier_name,
                                      "total_amount": new.total_amount,
                                      "lead_time_days": max(i["lead_time_days"] for i in g["items"])})
            result["queued_conversations"].append(conv.id)
        result["status"] = "replaced"
        return result
    mats = {i["material_id"] for i in before["items"]}
    needs = [date.fromisoformat(i["needed_by_date"]) for i in before["items"] if i.get("needed_by_date")]
    schedules = affected_schedules(db, mats, max(needs) if needs else None)
    options = []
    if groups:
        names = ", ".join(g["supplier_name"] for g in groups)
        options.append(_resource_option(groups, f"A new PO is issued to {names} even though it is outside the "
                                                "agent's limits.", warnings))
    options.append({"key": "continue_project", "label": OPTION_LABEL["continue_project"],
                    "effect": "Production schedules stay; the material shortage shows in MPS & Planning (run marked "
                              "for re-planning) so another source can be found manually.",
                    "schedules": schedules})
    if schedules:
        options.append({"key": "cancel_project", "label": OPTION_LABEL["cancel_project"],
                        "effect": f"{len(schedules)} production schedule(s) using this material are cancelled "
                                  "(check MPS & Planning).", "schedules": schedules})
    cr = POChangeRequest(kind="CANCELLATION", po_id=po.id, po_number=before["po_number"], po_snapshot=snap,
                         conversation_id=None, supplier_id=before["supplier_id"],
                         proposed_changes=[{"po_item_id": None, "sku": before["po_number"], "name": "", "uom": None,
                                            "field": "status", "old": before["status"], "new": "CANCELLED",
                                            "reason": reason}],
                         invalid_changes=[], supplier_message=supplier_message, options=options,
                         status=CRS.PENDING_MANAGER)
    db.add(cr)
    db.flush()
    result["change_request_id"] = cr.id
    return result


# ------------------------------------- manager choices -------------------------------------
def _supplier_msg(result: dict, cr: POChangeRequest, text: str, revision_id: int | None = None) -> None:
    result["supplier_messages"].append({"supplier_id": cr.supplier_id, "conversation_id": cr.conversation_id,
                                        "text": text, "revision_id": revision_id})


def _resource(db: Session, cr: POChangeRequest, option: dict, actor: str, action_id, result: dict, why: str) -> None:
    for group in option["purchase_orders"]:
        new = create_and_issue_po(db, group, actor, notes=f"Replacement for {cr.po_number} ({why})")
        new_conv = queue_conversation(db, new, ConversationPurpose.CONFIRM_ORDER, action_id)
        result["new_pos"].append({"id": new.id, "po_number": new.po_number, "supplier_name": new.supplier_name,
                                  "total_amount": new.total_amount})
        result["queued_conversations"].append(new_conv.id)


def _revise(db: Session, po: PurchaseOrder, cr: POChangeRequest, conv, changes: list[dict], actor: str,
            action_id, result: dict) -> None:
    """Applies line changes (approved or negotiated) as a new PO version and asks the supplier to confirm."""
    po_service.apply_supplier_revision(db, po, [{"po_item_id": c["po_item_id"], "field": c["field"], "new": c["new"]}
                                                for c in changes])
    if not revisions(db, po.id):                          # PO sent before version history existed
        _add_revision(db, po, cr.po_snapshot, [], None)
    rev = _add_revision(db, po, po_snapshot(po), changes, actor, change_request_id=cr.id)
    result["revision"] = {"id": rev.id, "version": rev.version}
    conf = confirmation(db, po.id)
    conf.revision_round += 1
    conf.status = SCS.PENDING
    if conv:
        close_conversation(conv, CS.CLOSED, change_request_id=cr.id, result=result["choice"])
    new_conv = queue_conversation(db, po, ConversationPurpose.REVISION_CONFIRM, action_id, change_request_id=cr.id)
    collected = (conv.outcome or {}).get("collected") if conv else None
    if collected:                                       # mis. tanggal kirim yang sudah disebut supplier
        new_conv.outcome = {"collected": collected}
    result["queued_conversations"].append(new_conv.id)
    result["total_after"] = po.total_amount


def _counter_changes(cr: POChangeRequest, counter_prices: dict | None) -> list[dict]:
    prices = {int(k): v for k, v in (counter_prices or {}).items()}
    out = []
    for c in cr.proposed_changes:
        if c["field"] != "unit_price":
            continue
        if c["po_item_id"] not in prices:
            raise AppError(422, f"Enter a counter price for {c['sku']} {c['name']}")
        price = parse_rupiah(prices[c["po_item_id"]]) if isinstance(prices[c["po_item_id"]], str) \
            else int(prices[c["po_item_id"]])
        if price < 0:
            raise AppError(422, "The counter price cannot be negative")
        out.append({**c, "new": price, "asked": c["new"]})
    if not out:
        raise AppError(422, "There is no price to negotiate")
    return out


def apply_change_request(db: Session, cr: POChangeRequest, choice: str, actor: str, params: dict | None = None) -> dict:
    """Executes the manager's (or, within the limits, the agent's) choice.

    `params`: counter_prices {po_item_id: price} for `negotiate`, schedule_ids for `cancel_project`.
    Returns ids of new POs / queued conversations, `notices` (withdrawals) and `supplier_messages`;
    outbound Telegram messages are NOT sent here, the caller sends them after the commit.
    """
    params = params or {}
    if cr.status not in (CRS.PENDING_MANAGER, CRS.AWAITING_MANAGER_CONFIRM):
        raise AppError(409, f"Request #{cr.id} was already processed ({cr.status.value})")
    option = next((o for o in cr.options if o["key"] == choice), None)
    if option is None:
        raise AppError(422, f"Option '{choice}' is not available for request #{cr.id}")
    po = None
    if cr.kind != "CANCELLATION":
        po = _get_po(db, cr.po_id)
        _check_snapshot(po, cr.po_snapshot)
    conv = db.get(SupplierConversation, cr.conversation_id) if cr.conversation_id else None
    action_id = conv.automation_action_id if conv else None
    result = {"choice": choice, "kind": cr.kind, "po_number": cr.po_number, "new_pos": [], "queued_conversations": [],
              "notices": [], "supplier_messages": []}

    if choice == "approve_change":
        _revise(db, po, cr, conv, cr.proposed_changes, actor, action_id, result)
        cr.status = CRS.CHANGE_APPROVED
    elif choice == "negotiate":
        changes = _counter_changes(cr, params.get("counter_prices") or (cr.result or {}).get("pending_counter"))
        _revise(db, po, cr, conv, changes, actor, action_id, result)
        result["applied_changes"] = changes
        cr.status = CRS.CHANGE_APPROVED
    elif choice == "accept_date":
        new = cr.proposed_changes[0]["new"]
        if conv is not None:                          # date from the first confirmation -> final confirmation
            collected = (conv.outcome or {}).get("collected") or {}
            record_supplier_confirmation(db, conv, new, collected.get("supplier_reference"))
            rev = finalize_po_revision(db, po)
            note_action(db, action_id, supplier_outcome=f"{po.po_number} confirmed (delivery date {new} approved by the manager)")
        else:
            rev = revise_promised_date(db, po, new, actor, change_request_id=cr.id)
        result["revision"] = {"id": rev.id, "version": rev.version}
        _supplier_msg(result, cr, f"We accept {new} as the delivery date for {po.po_number}. Attached is PO version "
                                  f"{rev.version} for your reference.", rev.id)
        cr.status = CRS.CHANGE_APPROVED
    elif choice == "reject_date":
        dl = cr.proposed_changes[0].get("deadline")
        old = cr.proposed_changes[0].get("old")
        if conv is not None:
            conv.status, conv.last_activity_at = CS.AWAITING_SUPPLIER, now()
            confirmation(db, po.id).status = SCS.PENDING
            ask = f"Please let us know a delivery date no later than {dl}." if dl else \
                "Please let us know another delivery date."
        else:
            ask = (f"The agreed delivery date ({old}) still applies." if old else "") + \
                  (f" Please deliver by {dl}." if dl else "")
        _supplier_msg(result, cr, f"Sorry, we cannot accept {cr.proposed_changes[0]['new']} as the delivery date for "
                                  f"{cr.po_number}. {ask}".strip())
        cr.status = CRS.ABORTED
    elif choice == "abort":
        if conv:
            close_conversation(conv, CS.CLOSED, change_request_id=cr.id, result="aborted")
        snap = cancel_po(db, po.id, "manager rejected the supplier's request")
        result["notices"].append({"supplier_id": cr.supplier_id, "conversation_id": cr.conversation_id, "snapshot": snap})
        note_action(db, action_id, supplier_outcome=f"{snap['po_number']} cancelled by the manager after the supplier's request")
        cr.status = CRS.ABORTED
    elif choice == "resource":
        _resource(db, cr, option, actor, action_id, result,
                  "original PO cancelled" if cr.kind == "CANCELLATION" else "supplier request not accepted")
        if cr.kind != "CANCELLATION":                     # issue the replacement FIRST, then cancel the old PO
            if conv:
                close_conversation(conv, CS.CLOSED, change_request_id=cr.id, result="resourced")
            snap = cancel_po(db, po.id, "moved to " + ", ".join(p["po_number"] for p in result["new_pos"]))
            result["notices"].append({"supplier_id": cr.supplier_id, "conversation_id": cr.conversation_id,
                                      "snapshot": snap})
            note_action(db, action_id, supplier_outcome=f"{snap['po_number']} moved to "
                                                        + ", ".join(p["po_number"] for p in result["new_pos"]))
        cr.status = CRS.RESOURCED
    elif choice == "continue_project":
        planning_service.mark_runs_stale(db)
        result["schedules"] = option.get("schedules", [])
        cr.status = CRS.CHANGE_APPROVED
    elif choice == "cancel_project":
        allowed = {s["id"] for s in option.get("schedules", [])}
        wanted = set(params.get("schedule_ids") or allowed) & allowed
        if not wanted:
            raise AppError(422, "Select at least one production schedule to cancel")
        cancelled = []
        for sid in sorted(wanted):
            s = db.get(Schedule, sid)
            if s is not None and s.status == ScheduleStatus.PLANNED:
                schedule_service.change_status(db, s, ScheduleStatus.CANCELLED)
                cancelled.append(s.batch_code)
        result["cancelled_schedules"] = cancelled
        cr.status = CRS.ABORTED
    cr.manager_choice, cr.pending_choice, cr.decided_at = choice, None, now()
    cr.result = {**{k: v for k, v in (cr.result or {}).items() if k != "pending_counter"},
                 **{k: v for k, v in result.items() if k not in ("notices", "supplier_messages")}, "decided_by": actor}
    db.flush()
    return result
