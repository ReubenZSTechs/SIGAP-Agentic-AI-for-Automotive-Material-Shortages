"""WRITE tools for purchase orders, used by the PO automation and supplier-chat agents.

The LLM never calls these with free parameters: callers pass ids taken from DB records
(automation proposals, conversations, change requests). Business rules live here and in
`po_service` (status machine, stale-run marking); agents only classify and write text.
"""
import re
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, func, literal, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import AppError
from app.database import engine
from app.models import (AutomationAction, Inventory, Material, POChangeRequest, POItem, PORevision,
                        POSupplierConfirmation,
                        PurchaseOrder, Supplier, SupplierConversation)
from app.models.enums import (ChangeRequestStatus, ConversationPurpose, ConversationStatus, ItemCategory,
                              PORevisionStatus, POSource, POStatus, SupplierConfirmationStatus)
from app.services import allocation_service, master_service, planning_service, po_service
from configs.tools.curated import resolve_materials

CS, CRS, SCS, RS = ConversationStatus, ChangeRequestStatus, SupplierConfirmationStatus, PORevisionStatus
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


FIELD_LABEL = {"qty_ordered": "qty", "unit_price": "harga satuan", "needed_by_date": "tanggal kebutuhan"}


def change_value(field: str, v) -> str:
    if field == "unit_price":
        return rupiah(v)
    if field == "qty_ordered":
        return fmt_qty(v)
    return str(v)


def describe_change(c: dict) -> str:
    """`{sku, name, field, old, new}` -> "RM-RUB-01 Ban Luar Karet: qty 50 → 40" (exact, never LLM-written)."""
    return (f"{c['sku']} {c['name']}: {FIELD_LABEL.get(c['field'], c['field'])} {change_value(c['field'], c['old'])} → "
            f"{change_value(c['field'], c['new'])}")


def revision_diff_text(changes: list[dict], total_before: int, total_after: int) -> str:
    """What changed in an approved revision (sent to the supplier instead of the full PO again)."""
    lines = ["Perubahan yang disetujui:", *[f"- {describe_change(c)}" for c in changes]]
    if total_before != total_after:
        lines.append(f"Total: {rupiah(total_before)} → {rupiah(total_after)}")
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


def assign_suppliers(db: Session, needs: list[dict], deadline: date | None = None, today: date | None = None,
                     order_qty=None) -> dict:
    """Chooses one supplier per material, cross-checked over ALL materials so that fewer POs are needed.

    `needs`: [{material_id, sku, name, uom, qty}]. With `deadline`, only links that can arrive in time
    (today + lead time <= deadline) are candidates; a material nobody can deliver in time gets its
    fastest link and a warning. `order_qty(need, link)` gives the quantity ordered from a link
    (default: the needed qty).

    Greedy cover: repeatedly take the supplier that can supply the most still-unassigned materials
    (ties: fewer MOQ shortfalls, more preferred links, lower cost, shorter lead time, code), assign
    those materials to it, repeat. One supplier that sells several of the materials therefore gets
    them all on one PO, even when another supplier is a little cheaper for one of them.

    Returns {assigned: [(link, need, qty, late)], missing: [need], warnings: [...],
    extra_cost: consolidated cost - cheapest-per-material cost, saved_pos: POs avoided}.
    """
    today = today or date.today()
    order_qty = order_qty or (lambda need, link: need["qty"])
    cands, late, missing, warnings = {}, set(), [], []
    for n, need in enumerate(needs):
        links = active_links(db, need["material_id"])
        if not links:
            missing.append(need)
            continue
        ok = [l for l in links if deadline is None or today + timedelta(days=l["lead_time_days"]) <= deadline]
        if not ok:
            fastest = min(links, key=lambda l: (l["lead_time_days"], l["unit_price"], l["supplier_code"]))
            ok, earliest = [fastest], today + timedelta(days=fastest["lead_time_days"])
            late.add(n)
            warnings.append(f"{need['sku']}: {fastest['supplier_name']} paling cepat tiba {earliest.isoformat()} "
                            f"(setelah {deadline.isoformat()})")
        cands[n] = {l["supplier_id"]: l for l in ok}

    def cost(n, link):
        return order_qty(needs[n], link) * link["unit_price"]

    unassigned, assigned, chosen_cost = set(cands), [], 0
    while unassigned:
        suppliers = {sid for n in unassigned for sid in cands[n]}

        def score(sid):
            covered = [n for n in unassigned if sid in cands[n]]
            links = [cands[n][sid] for n in covered]
            return (-len(covered), sum(needs[n]["qty"] < l["moq"] for n, l in zip(covered, links)),
                    -sum(l["is_preferred"] for l in links), sum(cost(n, cands[n][sid]) for n in covered),
                    max(l["lead_time_days"] for l in links), links[0]["supplier_code"])
        best = min(suppliers, key=score)
        for n in sorted(n for n in unassigned if best in cands[n]):
            link = cands[n][best]
            assigned.append((link, needs[n], order_qty(needs[n], link), n in late))
            chosen_cost += cost(n, link)
            unassigned.discard(n)
    cheapest = sum(min(cost(n, l) for l in cands[n].values()) for n in cands)
    cheapest_suppliers = {min(cands[n].values(), key=lambda l: (cost(n, l), l["supplier_code"]))["supplier_id"]
                          for n in cands}
    used = {a[0]["supplier_id"] for a in assigned}
    return {"assigned": assigned, "missing": missing, "warnings": warnings,
            "extra_cost": round(chosen_cost - cheapest), "saved_pos": max(0, len(cheapest_suppliers) - len(used))}


def consolidation_note(result: dict) -> str | None:
    if result["saved_pos"] <= 0:
        return None
    extra = result["extra_cost"]
    cost = f"+{rupiah(extra)} dibanding pemasok termurah per material, " if extra > 0 else ""
    return f"Material digabung per supplier: {cost}hemat {result['saved_pos']} PO."


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


def cancel_po(db: Session, po_id: int, reason: str, snapshot: dict | None = None) -> dict:
    """Cancels an issued PO but keeps it (status CANCELLED, "Dibatalkan"); returns the PO snapshot."""
    po = _get_po(db, po_id)
    if snapshot is not None:
        _check_snapshot(po, snapshot)
    snap = po_snapshot(po)
    po_service.cancel_issued(db, po, reason)
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
CONFIRMATION_FIELDS = {"promised_delivery_date": "tanggal pengiriman",
                       "supplier_reference": "nomor referensi/pesanan dari pihak Anda"}


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


def valid_future_date(value) -> str | None:
    """YYYY-MM-DD from an agent field, or None when missing, invalid or in the past."""
    try:
        d = date.fromisoformat(str(value).strip()) if value else None
    except ValueError:
        return None
    return d.isoformat() if d and d >= date.today() else None


def missing_fields_text(po_number: str, missing: list[str]) -> str:
    asks = " dan ".join(CONFIRMATION_FIELDS.get(f, f) for f in missing)
    return f"Terima kasih atas konfirmasinya untuk {po_number}. Mohon informasikan {asks} agar PO dapat kami finalkan."


def split_promised_dates(po: PurchaseOrder, proposed: list[dict]) -> tuple[str | None, list[dict]]:
    """A delivery date for a line that has no needed-by date is the supplier's promise, not a revision.

    Returns (latest such date as YYYY-MM-DD or None, the remaining proposed changes).
    """
    promised, rest = None, []
    for pc in proposed or []:
        line = _match_line(po, pc.get("material_ref"))
        if _FIELD.get(pc.get("field")) == "needed_by_date" and line is not None and line.needed_by_date is None:
            try:
                d = date.fromisoformat(str(pc.get("new_value")).strip()).isoformat()
            except ValueError:
                rest.append(pc)
                continue
            promised = max(promised or d, d)
            continue
        rest.append(pc)
    return promised, rest


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
                "effect": f"{po.po_number} dibatalkan (status Dibatalkan, data PO tetap tersimpan; stok on-order "
                          "dikembalikan) dan supplier diberi tahu."}]
    if valid and not invalid and po.status == POStatus.ISSUED and not _has_receipts(po) \
            and conf.revision_round < max_revision_rounds:
        changes = {(c["po_item_id"], c["field"]): c["new"] for c in valid}
        after = []
        for it in snap["items"]:
            line = {**it, **{f: changes[(it["po_item_id"], f)] for f in _FIELD.values() if (it["po_item_id"], f) in changes}}
            line["line_total"] = round(line["qty_ordered"] * line["unit_price"])
            after.append(line)
        options.append({"key": "approve_change", "label": "Setujui perubahan",
                        "effect": f"{po.po_number} direvisi; supplier menerima daftar perubahannya untuk dikonfirmasi.",
                        "items_after": after, "total_before": po.total_amount,
                        "total_after": sum(i["line_total"] for i in after)})
    alternatives = find_alternative_suppliers(db, po)
    if alternatives:
        names = ", ".join(g["supplier_name"] for g in alternatives)
        options.append({"key": "resource", "label": "Pesan ke supplier lain",
                        "effect": f"PO baru diterbitkan ke {names}; {po.po_number} dibatalkan (tetap tersimpan) dan "
                                  "supplier lama diberi tahu.",
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
        if not revisions(db, po.id):                          # PO dikirim sebelum riwayat versi ada
            _add_revision(db, po, cr.po_snapshot, [], None)
        rev = _add_revision(db, po, po_snapshot(po), cr.proposed_changes, actor, change_request_id=cr.id)
        result["revision"] = {"id": rev.id, "version": rev.version}
        conf = confirmation(db, po.id)
        conf.revision_round += 1
        conf.status = SCS.PENDING
        if conv:
            close_conversation(conv, CS.CLOSED, change_request_id=cr.id, result="change_approved")
        new_conv = queue_conversation(db, po, ConversationPurpose.REVISION_CONFIRM, action_id, change_request_id=cr.id)
        collected = (conv.outcome or {}).get("collected") if conv else None
        if collected:                                       # mis. tanggal kirim yang sudah disebut supplier
            new_conv.outcome = {"collected": collected}
        result["queued_conversations"].append(new_conv.id)
        result["total_after"] = po.total_amount
        cr.status = CRS.CHANGE_APPROVED
    elif choice == "abort":
        if conv:
            close_conversation(conv, CS.CLOSED, change_request_id=cr.id, result="aborted")
        snap = cancel_po(db, po.id, "manajer menolak permintaan revisi supplier")
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
        snap = cancel_po(db, po.id, "dialihkan ke " + ", ".join(p["po_number"] for p in result["new_pos"]))
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
    "cancel_po": cancel_po,
    "request_po_cancellation": request_po_cancellation,
    "queue_conversation": queue_conversation,
    "ensure_confirm_conversation": ensure_confirm_conversation,
    "finalize_po_revision": finalize_po_revision,
    "record_supplier_confirmation": record_supplier_confirmation,
    "record_supplier_decline": record_supplier_decline,
    "open_change_request": open_change_request,
    "apply_change_request": apply_change_request,
}
