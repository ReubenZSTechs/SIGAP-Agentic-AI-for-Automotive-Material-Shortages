"""Turns a parsed PO request from the chat into a proposal (read-only): create, update, delete, produce."""
import re
from collections import defaultdict
from datetime import date

from sqlalchemy import and_, func, literal, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (
    Inventory,
    Material,
    POItem,
    POSupplierConfirmation,
    PurchaseOrder,
    Supplier,
    SupplierConversation,
)
from app.models.enums import ConversationPurpose, ItemCategory, POSource, POStatus
from app.services import allocation_service, planning_service, po_service
from configs.tools.curated import resolve_materials
from configs.tools.po_common import (
    EDITABLE,
    MAX_OPTIONS,
    OPEN_CONVERSATION,
    _has_receipts,
    _iso,
    fmt_qty,
    po_snapshot,
    rupiah,
)
from configs.tools.po_sourcing import _group_by_supplier, _line, active_links, assign_suppliers, consolidation_note


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
    """Active suppliers by exact code, a code inside a label ("SUP-CPT CV Cipta Logam"), part of a
    code/name ("Cipta"), or a label that contains the full name ("supplier CV Cipta Logam")."""
    term = term.strip()
    active = Supplier.is_active
    exact = db.scalars(select(Supplier).where(func.lower(Supplier.code) == term.lower(), active)).all()
    if exact:
        return list(exact)
    codes = {c.lower() for c in re.findall(r"[A-Za-z]{2,}-[A-Za-z0-9]+", term)}
    if codes:
        hits = db.scalars(select(Supplier).where(func.lower(Supplier.code).in_(codes), active)).all()
        if hits:
            return list(hits)
    hits = db.scalars(select(Supplier).where(active, Supplier.code.ilike(f"%{term}%") | Supplier.name.ilike(f"%{term}%"))
                      .limit(MAX_OPTIONS)).all()
    if hits:
        return list(hits)
    return list(db.scalars(select(Supplier).where(active, literal(term).ilike(func.concat("%", Supplier.name, "%")))
                           .order_by(Supplier.code).limit(MAX_OPTIONS)))


def _supplier_options(db: Session, materials: list[Material]) -> list[dict]:
    """Active suppliers of every given material, as clarification options."""
    by_code = {}
    for m in materials:
        for l in active_links(db, m.id):
            detail = f" ({rupiah(l['unit_price'])}, {l['lead_time_days']} hari)" if len(materials) == 1 else ""
            by_code.setdefault(l["supplier_code"], {"label": f"{l['supplier_code']} {l['supplier_name']}{detail}",
                                                    "value": l["supplier_code"]})
    return list(by_code.values())[:MAX_OPTIONS]


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


def material_ids(db: Session, items: list[dict]) -> set[int]:
    """Ids of every purchasable material an item list may refer to (all candidates of each query)."""
    return {m.id for it in items or [] for m in resolve_materials(db, it.get("material_query") or "",
                                                                  (ItemCategory.PURCHASED,), limit=MAX_OPTIONS)}


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
    supplier, supplier_missing = None, False
    if draft.get("supplier_query"):
        sups = _find_suppliers(db, draft["supplier_query"])
        if not sups:
            supplier_missing = True                         # opsi supplier ditambahkan setelah material diketahui
        elif len(sups) > 1:
            out["ambiguous"].append({"field": "supplier", "message": "Several suppliers match.",
                                     "options": [{"label": f"{s.code} {s.name}", "value": s.code} for s in sups]})
        else:
            supplier = sups[0]
    needed_by = _parse_date(draft.get("needed_by_date"), "needed_by_date", out, today)
    merged: dict[int, tuple[Material, float]] = {}
    found: dict[int, Material] = {}
    for n, it in enumerate(items):
        m = _resolve_material(db, it.get("material_query") or "", f"items.{n}.material", out)
        if m is not None:
            found[m.id] = m
        qty = it.get("qty")
        if qty is None or qty <= 0:
            what = m.name if m else (it.get("material_query") or "this material")
            out["missing"].append({"field": f"items.{n}.qty", "message": f"How many {what}?"})
            continue
        if m is not None:
            merged[m.id] = (m, merged.get(m.id, (m, 0))[1] + qty)
    if supplier_missing:
        options = _supplier_options(db, list(found.values()))
        message = f"Supplier '{draft['supplier_query']}' was not found."
        if options:
            out["ambiguous"].append({"field": "supplier", "message": f"{message} Choose one of the active suppliers "
                                                                     "for this material.", "options": options})
        else:
            out["errors"].append({"field": "supplier", "message": message})
        return
    lines, warnings = [], []
    if supplier is not None:                                # supplier disebut pengguna: dipakai untuk semua material
        chosen = []
        for m, qty in merged.values():
            links = active_links(db, m.id)
            link = next((l for l in links if l["supplier_id"] == supplier.id), None)
            if link is None:
                out["ambiguous"].append({
                    "field": "supplier", "message": f"{supplier.name} does not supply {m.sku} {m.name}.",
                    "options": [{"label": f"{l['supplier_code']} {l['supplier_name']} ({rupiah(l['unit_price'])}, "
                                          f"{l['lead_time_days']} hari)", "value": l["supplier_code"]} for l in links]})
                continue
            chosen.append((link, m, qty))
    else:                                                   # pilih supplier lintas material (PO sesedikit mungkin)
        needs = [{"material_id": m.id, "sku": m.sku, "name": m.name, "uom": m.uom, "qty": qty, "material": m}
                 for m, qty in merged.values()]
        pick = assign_suppliers(db, needs)
        for need in pick["missing"]:
            out["errors"].append({"field": "supplier",
                                  "message": f"No active supplier can deliver {need['sku']} {need['name']}."})
        chosen = [(link, need["material"], qty) for link, need, qty, _ in pick["assigned"]]
        if consolidation_note(pick):
            warnings.append(consolidation_note(pick))
    for link, m, qty in chosen:
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


# ------------------------------ production request (schedule + POs) ------------------------------
def _incoming_by(db: Session, by: date) -> dict[int, float]:
    """Open PO quantity per material that is expected by `by`: the supplier's promised delivery date,
    else the line's needed-by date, must be on or before `by` (undated / late lines do not count)."""
    counted = or_(*[and_(PurchaseOrder.source == src, PurchaseOrder.status.in_(sts))
                    for src, sts in planning_service.COUNTED.items()])
    rows = db.execute(select(POItem.material_id, POItem.qty_ordered - POItem.qty_received, POItem.needed_by_date,
                             POSupplierConfirmation.promised_delivery_date)
                      .join(PurchaseOrder, POItem.po_id == PurchaseOrder.id)
                      .outerjoin(POSupplierConfirmation, POSupplierConfirmation.po_id == PurchaseOrder.id)
                      .where(counted))
    out: dict[int, float] = defaultdict(float)
    for mid, remaining, needed, promised in rows:
        arrives = promised or needed
        if arrives is not None and arrives <= by and remaining > 0:
            out[mid] += remaining
    return out


def _resolve_produce(db: Session, draft: dict, out: dict, today: date) -> None:
    """"Saya membutuhkan 100 sepeda gunung besok": BOM requirement vs stock, then one PO per supplier for
    every material that would fall below its safety stock, plus the production schedule itself."""
    items = draft.get("items") or []
    if not items:
        out["missing"].append({"field": "items", "message": "Which product and how many units?"})
        return
    when = _parse_date(draft.get("needed_by_date"), "needed_by_date", out, today)
    if not draft.get("needed_by_date"):
        out["missing"].append({"field": "needed_by_date", "message": "By which date must the materials be ready "
                                                                     "(production date)?"})
    products: dict[int, tuple[Material, int]] = {}
    for n, it in enumerate(items):
        found = [m for m in resolve_materials(db, it.get("material_query") or "", (ItemCategory.FINISHED,),
                                              limit=MAX_OPTIONS) if m.is_active]
        qty = it.get("qty")
        if not found:
            out["errors"].append({"field": f"items.{n}.product",
                                  "message": f"No finished product matches '{it.get('material_query')}'."})
        elif len(found) > 1:
            out["ambiguous"].append({"field": f"items.{n}.product", "message": "Which product?",
                                     "options": [{"label": f"{m.sku} {m.name}", "value": m.sku} for m in found]})
        if qty is None or qty <= 0:
            out["missing"].append({"field": f"items.{n}.qty", "message": "How many units to produce?"})
        elif float(qty) != int(qty):
            out["errors"].append({"field": f"items.{n}.qty", "message": "Production quantity must be a whole number."})
        elif len(found) == 1:
            m = found[0]
            products[m.id] = (m, products.get(m.id, (m, 0))[1] + int(qty))
    if out["missing"] or out["ambiguous"] or out["errors"] or when is None:
        return
    need_by = date.fromisoformat(when)
    requirement: dict[int, float] = defaultdict(float)
    for m, qty in products.values():
        try:
            for mid, q in allocation_service.requirement(db, m.id, qty).items():
                requirement[mid] += q
        except AppError as e:
            out["errors"].append({"field": "bom", "message": f"{m.sku} {m.name}: {e.detail}"})
    if out["errors"]:
        return
    mats = {m.id: m for m in db.scalars(select(Material).where(Material.id.in_(list(requirement))))}
    invs = {i.material_id: i for i in db.scalars(select(Inventory).where(Inventory.material_id.in_(list(requirement))))}
    incoming = _incoming_by(db, need_by)
    check, needs = [], []
    for mid, req in sorted(requirement.items(), key=lambda kv: mats[kv[0]].sku):
        m, inv = mats[mid], invs.get(mid)
        on_hand, allocated, safety = (inv.on_hand, inv.allocated, inv.safety_stock) if inv else (0.0, 0.0, 0.0)
        available = round(on_hand - allocated, 6)
        after = round(available - req, 6)
        arriving = round(incoming.get(mid, 0.0), 6)
        shortfall = round(max(0.0, safety - (after + arriving)), 6)   # sama dengan rumus run MRP (ke batas aman)
        check.append({"material_id": mid, "sku": m.sku, "name": m.name, "uom": m.uom, "requirement": req,
                      "available": available, "available_after": after, "incoming_in_time": arriving,
                      "safety_stock": safety, "shortfall": shortfall,
                      "status_without_po": planning_service.classify(after + arriving, safety).value})
        if shortfall > 0:
            needs.append({"material_id": mid, "sku": m.sku, "name": m.name, "uom": m.uom, "qty": shortfall})
    pick = assign_suppliers(db, needs, deadline=need_by, today=today,
                            order_qty=lambda need, link: max(need["qty"], link["moq"]))
    for need in pick["missing"]:
        out["errors"].append({"field": "supplier", "message": f"No active supplier can deliver {need['sku']} {need['name']}."})
    if out["errors"]:
        return
    lines = [(link, _line(link, need, qty, when)) for link, need, qty, _ in pick["assigned"]]
    pos = _group_by_supplier(db, lines) if lines else []
    warnings = list(pick["warnings"])
    if consolidation_note(pick):
        warnings.append(consolidation_note(pick))
    schedules = [{"product_id": m.id, "sku": m.sku, "name": m.name, "uom": m.uom, "qty": qty,
                  "production_date": when} for m, qty in products.values()]
    out["proposal"] = {"operation": "produce", "request": draft, "schedules": schedules, "materials": check,
                       "purchase_orders": pos, "grand_total": sum(p["total_amount"] for p in pos),
                       "needed_by_date": when, "warnings": warnings}


def produce_signature(p: dict) -> list:
    """What must not change between the card and its execution (schedules, PO lines, prices)."""
    return sorted([("S", s["product_id"], s["qty"], s["production_date"]) for s in p["schedules"]]
                  + [("L", g["supplier_id"], i["material_id"], i["qty_ordered"], i["unit_price"])
                     for g in p["purchase_orders"] for i in g["items"]])


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
    elif op == "produce":
        _resolve_produce(db, draft, out, today)
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
