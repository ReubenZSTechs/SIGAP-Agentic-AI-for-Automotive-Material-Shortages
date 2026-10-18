"""Deterministic read-only tools that reuse the existing MRP services."""
import difflib
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.chatbot.semantic_views import OPEN_PO_STATUSES
from app.models import (Material, MaterialSupplier, PlanningRun, PurchaseOrder, Schedule, Supplier)
from app.models.enums import ItemCategory, ScheduleStatus, StockStatus
from app.services import bom_service, inventory_service, master_service, planning_service

ToolOutput = tuple[list[dict], dict]

_SEVERITY = {StockStatus.CRITICAL.value: 0, StockStatus.WARNING.value: 1, StockStatus.SAFE.value: 2}
MAX_MATCHES = 5


def _like(term: str) -> str:
    return f"%{term.strip()}%"


def resolve_materials(db: Session, term: str, categories: tuple[ItemCategory, ...] | None = None,
                      limit: int = MAX_MATCHES) -> list[Material]:
    """Fuzzy material lookup: exact SKU, then substring, then all-words, then close names."""
    base = select(Material)
    if categories:
        base = base.where(Material.category.in_(categories))
    term = (term or "").strip()
    if not term:
        return []
    exact = db.scalars(base.where(func.lower(Material.sku) == term.lower())).all()
    if exact:
        return list(exact)
    found = db.scalars(base.where(or_(Material.sku.ilike(_like(term)), Material.name.ilike(_like(term))))
                       .order_by(Material.sku).limit(limit)).all()
    if found:
        return list(found)
    words = [w for w in term.split() if len(w) > 1]
    if words:
        found = db.scalars(base.where(*[Material.name.ilike(_like(w)) for w in words])
                           .order_by(Material.sku).limit(limit)).all()
        if found:
            return list(found)
    pool = db.scalars(base).all()
    names = {m.name.lower(): m for m in pool}
    close = difflib.get_close_matches(term.lower(), list(names), n=limit, cutoff=0.6)
    return [names[n] for n in close]


def _match_meta(term: str, matches: list[Material]) -> dict:
    meta = {"search_term": term, "matched": [f"{m.sku} {m.name}" for m in matches]}
    if not matches:
        meta["note"] = f"No item matches '{term}'."
    elif len(matches) > 1:
        meta["note"] = f"'{term}' matched {len(matches)} items; results include all of them."
    return meta


def _inventory_rows(db: Session) -> list[dict]:
    categories = dict(db.execute(select(Material.id, Material.category)).all())
    rows = inventory_service.list_inventory(db)
    for r in rows:
        r["category"] = categories.get(r["material_id"])
        r["shortfall"] = max(0.0, r["safety_stock"] - (r["available"] + r["on_order"]))
    return rows


def _project(row: dict, columns: list[str]) -> dict:
    return {c: row.get(c) for c in columns}


_STOCK_COLUMNS = ["sku", "name", "category", "uom", "on_hand", "allocated", "available",
                  "safety_stock", "on_order", "shortfall", "status"]


def get_stock_summary(db: Session, category: str | None = None, status: str | None = None,
                      **_) -> ToolOutput:
    """Current stock per item (on hand, allocated, available, safety, on order, status)."""
    rows = _inventory_rows(db)
    if category:
        rows = [r for r in rows if getattr(r["category"], "value", r["category"]) == category]
    if status:
        rows = [r for r in rows if r["status"].value == status]
    counts = {s.value: 0 for s in StockStatus}
    for r in rows:
        counts[r["status"].value] += 1
    return [_project(r, _STOCK_COLUMNS) for r in rows], {"item_count": len(rows), "status_counts": counts}


def get_critical_items(db: Session, include_warning: bool | None = None, **_) -> ToolOutput:
    """Items with CRITICAL (and optionally WARNING) stock status, most severe first."""
    wanted = {StockStatus.CRITICAL.value} | ({StockStatus.WARNING.value} if include_warning else set())
    rows = [r for r in _inventory_rows(db) if r["status"].value in wanted]
    rows.sort(key=lambda r: (_SEVERITY[r["status"].value], r["sku"]))
    return ([_project(r, _STOCK_COLUMNS) for r in rows],
            {"statuses_included": sorted(wanted), "item_count": len(rows),
             "rule": "CRITICAL: available <= 0; WARNING: 0 < available < safety_stock"})


def find_materials(db: Session, query: str | None = None, **_) -> ToolOutput:
    """Finds items by SKU or (partial/approximate) name."""
    matches = resolve_materials(db, query or "", limit=20)
    rows = [{"sku": m.sku, "name": m.name, "category": m.category, "uom": m.uom,
             "is_active": m.is_active} for m in matches]
    return rows, _match_meta(query or "", matches)


def get_material_suppliers(db: Session, material: str | None = None, **_) -> ToolOutput:
    """Suppliers for a material with price, lead time, MOQ and cheapest/fastest flags."""
    matches = resolve_materials(db, material or "")
    terms = {s.id: s.payment_term_days for s in db.scalars(select(Supplier))}
    rows = []
    for m in matches:
        for link in master_service.list_links(db, m.id):
            rows.append({"material_sku": m.sku, "material_name": m.name,
                         "supplier_code": link["supplier_code"], "supplier_name": link["supplier_name"],
                         "unit_price": link["unit_price"], "lead_time_days": link["lead_time_days"],
                         "moq": link["moq"], "payment_term_days": terms.get(link["supplier_id"]),
                         "is_preferred": link["is_preferred"], "is_active": link["is_active"],
                         "is_cheapest": link["is_cheapest"], "is_fastest": link["is_fastest"]})
    meta = _match_meta(material or "", matches)
    for m in matches:
        if not any(r["material_sku"] == m.sku for r in rows):
            meta.setdefault("without_suppliers", []).append(m.sku)
    return rows, meta


def list_suppliers(db: Session, query: str | None = None, **_) -> ToolOutput:
    """Suppliers (optionally filtered by code/name) with the materials they supply."""
    supplied: dict[int, list[str]] = {}
    for sid, sku in db.execute(select(MaterialSupplier.supplier_id, Material.sku)
                               .join(Material, Material.id == MaterialSupplier.material_id)
                               .where(MaterialSupplier.is_active).order_by(Material.sku)):
        supplied.setdefault(sid, []).append(sku)
    rows = [{"supplier_code": s.code, "supplier_name": s.name, "contact": s.contact,
             "payment_term_days": s.payment_term_days, "is_active": s.is_active,
             "material_count": len(supplied.get(s.id, [])),
             "materials": ", ".join(supplied.get(s.id, []))}
            for s in master_service.list_suppliers(db, query or None, None)]
    return rows, {"supplier_count": len(rows)}


def get_open_purchase_orders(db: Session, supplier: str | None = None, material: str | None = None,
                             **_) -> ToolOutput:
    """Open PO lines (not fully received, cancelled or rejected), optionally filtered."""
    stmt = select(PurchaseOrder).where(PurchaseOrder.status.in_(OPEN_PO_STATUSES)).order_by(PurchaseOrder.id)
    if supplier:
        stmt = stmt.join(Supplier, Supplier.id == PurchaseOrder.supplier_id).where(
            or_(Supplier.code.ilike(_like(supplier)), Supplier.name.ilike(_like(supplier))))
    skus = {m.sku for m in resolve_materials(db, material)} if material else None
    rows, po_numbers = [], set()
    for po in db.scalars(stmt):
        for it in po.items:
            if skus is not None and it.sku not in skus:
                continue
            po_numbers.add(po.po_number)
            rows.append({"po_number": po.po_number, "po_status": po.status, "po_source": po.source,
                         "supplier_name": po.supplier_name, "po_date": po.po_date, "sku": it.sku,
                         "material_name": it.name, "qty_ordered": it.qty_ordered,
                         "qty_received": it.qty_received, "qty_remaining": it.qty_ordered - it.qty_received,
                         "unit_price": it.unit_price, "line_total": it.line_total,
                         "needed_by_date": it.needed_by_date})
    totals = {po.po_number: po.total_amount for po in db.scalars(stmt) if po.po_number in po_numbers}
    return rows, {"open_po_count": len(po_numbers), "po_totals": totals,
                  "open_statuses": list(OPEN_PO_STATUSES)}


def get_latest_planning_run(db: Session, **_) -> ToolOutput:
    """Lines of the most recent planning run, most severe first, with run summary."""
    run = db.scalar(select(PlanningRun).order_by(PlanningRun.id.desc()).limit(1))
    if run is None:
        return [], {"note": "No planning run exists yet."}
    rows = [{"sku": l.sku, "material_name": l.material_name, "gross_requirement": l.gross_requirement,
             "on_hand": l.on_hand, "allocated": l.allocated, "available": l.available,
             "on_order": l.on_order, "safety_stock": l.safety_stock, "shortfall": l.shortfall,
             "status": l.status, "needed_by": l.needed_by,
             "selected_supplier_name": l.selected_supplier_name, "order_qty": l.order_qty}
            for l in planning_service.sorted_lines(run.lines)]
    meta = {"run_id": run.id, "date_from": run.date_from, "date_to": run.date_to,
            "run_status": run.status, "is_stale": run.is_stale, "created_at": run.created_at,
            **planning_service.summarize(run)}
    return rows, meta


def get_bom(db: Session, product: str | None = None, qty: float | None = None, **_) -> ToolOutput:
    """Multi-level BOM of a product/sub-part, with quantities for `qty` units."""
    qty = qty or 1
    matches = resolve_materials(db, product or "", (ItemCategory.FINISHED, ItemCategory.SUB_PART))
    meta = {**_match_meta(product or "", matches), "qty": qty}
    if not matches:
        return [], meta
    root = matches[0]
    if len(matches) > 1:
        meta["note"] = f"'{product}' matched {len(matches)} items; showing {root.sku}."
    rows = []

    def walk(node: dict, parent_sku: str | None):
        m = node["material"]
        if node["level"] > 0:
            rows.append({"level": node["level"], "parent_sku": parent_sku, "sku": m.sku, "name": m.name,
                         "category": m.category, "uom": m.uom, "qty_per_parent": node["qty_per_parent"],
                         "required_qty": round(node["qty_cumulative"] * qty, 6)})
        for child in node["children"]:
            walk(child, m.sku)

    walk(bom_service.build_tree(db, root.id), None)
    meta["product"] = f"{root.sku} {root.name}"
    return rows, meta


def get_production_schedules(db: Session, date_from: str | None = None, date_to: str | None = None,
                             schedule_status: str | None = None, **_) -> ToolOutput:
    """Production schedule batches, optionally filtered by date range and status."""
    stmt = select(Schedule).order_by(Schedule.production_date, Schedule.batch_code)
    if date_from:
        stmt = stmt.where(Schedule.production_date >= date.fromisoformat(date_from))
    if date_to:
        stmt = stmt.where(Schedule.production_date <= date.fromisoformat(date_to))
    if schedule_status:
        stmt = stmt.where(Schedule.status == ScheduleStatus(schedule_status))
    rows = [{"batch_code": s.batch_code, "product_sku": s.product_sku, "product_name": s.product_name,
             "line_code": s.line_code, "production_date": s.production_date,
             "target_qty": s.target_qty, "status": s.status} for s in db.scalars(stmt)]
    return rows, {"schedule_count": len(rows)}


CURATED = {
    "get_stock_summary": get_stock_summary,
    "get_critical_items": get_critical_items,
    "find_materials": find_materials,
    "get_material_suppliers": get_material_suppliers,
    "list_suppliers": list_suppliers,
    "get_open_purchase_orders": get_open_purchase_orders,
    "get_latest_planning_run": get_latest_planning_run,
    "get_bom": get_bom,
    "get_production_schedules": get_production_schedules,
}
