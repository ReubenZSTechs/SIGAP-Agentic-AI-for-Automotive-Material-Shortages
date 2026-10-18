"""Prompt-ready description of the relations the SQL agent may query."""
from app.database import Base

VIEW_CATALOG: dict[str, tuple[str, list[str]]] = {
    "chat_inventory_status_v": (
        "Current stock per item with business rules applied (one row per item).",
        ["material_id", "sku", "name", "category (FINISHED|SUB_PART|PURCHASED)", "uom", "is_active",
         "on_hand (stok fisik)", "allocated (stok terkunci by PLANNED schedules)",
         "available (= on_hand - allocated)", "safety_stock (batas aman)",
         "on_order (open PO qty not yet received)", "shortfall (= max(0, safety_stock - (available + on_order)))",
         "status (CRITICAL if available <= 0; WARNING if available < safety_stock; else SAFE)"],
    ),
    "chat_material_suppliers_v": (
        "Supplier offers per purchased material (one row per material-supplier link).",
        ["material_sku", "material_name", "supplier_code", "supplier_name", "unit_price (Rupiah)",
         "lead_time_days", "moq", "is_preferred", "is_active", "supplier_is_active",
         "payment_term_days", "is_cheapest (lowest active price for that material)",
         "is_fastest (shortest active lead time for that material)"],
    ),
    "chat_purchase_order_items_v": (
        "Every purchase order line with its header and supplier.",
        ["po_number", "po_status (DRAFT|PENDING_APPROVAL|APPROVED|REJECTED|ISSUED|PARTIALLY_RECEIVED|RECEIVED|CANCELLED)",
         "po_source (MANUAL|PLANNING)", "po_date", "is_open (not yet fully received/cancelled/rejected)",
         "po_total_amount (Rupiah, whole PO)", "planning_run_id", "supplier_code", "supplier_name",
         "sku", "material_name", "uom", "qty_ordered", "qty_received", "qty_remaining",
         "unit_price (Rupiah)", "line_total (Rupiah)", "needed_by_date"],
    ),
    "chat_latest_planning_lines_v": (
        "Lines of the most recent planning run (MRP net requirements snapshot).",
        ["run_id", "run_date_from", "run_date_to", "run_status (DRAFT|PO_GENERATED)", "run_is_stale",
         "run_created_at", "sku", "material_name", "uom", "gross_requirement", "on_hand", "allocated",
         "available", "on_order", "safety_stock", "shortfall", "status (CRITICAL|WARNING|SAFE)",
         "needed_by", "selected_supplier_name", "order_qty", "unit_price", "lead_time_days"],
    ),
    "chat_schedules_v": (
        "Production schedule batches (MPS).",
        ["batch_code", "product_sku", "product_name", "line_code", "line_name", "production_date",
         "target_qty", "status (PLANNED|IN_PROGRESS|COMPLETED|CANCELLED)", "started_at", "completed_at"],
    ),
    "chat_bom_v": (
        "Direct BOM edges (parent item -> component). Multi-level BOMs chain through SUB_PART items.",
        ["parent_sku", "parent_name", "parent_category", "child_sku", "child_name", "child_category",
         "child_uom", "qty_per_parent"],
    ),
}

BASE_TABLES = ("materials", "suppliers", "material_suppliers", "inventory", "stock_movements",
               "bom_items", "schedules", "production_lines", "planning_runs", "planning_lines",
               "purchase_orders", "po_items")

ALLOWED_RELATIONS = frozenset(VIEW_CATALOG) | frozenset(BASE_TABLES)

GLOSSARY = """Glossary (Indonesian UI term -> column): Stok Fisik = on_hand; Stok Terkunci = allocated;
Stok Tersedia = available; Batas Aman = safety_stock; Dipesan = on_order; Defisit = shortfall;
Material Beli = category PURCHASED; Sub-part = SUB_PART; Produk Final = FINISHED.
Money columns are integer Rupiah. stock_movements.qty is signed (+ in / - out);
stock_movements.type is GOODS_RECEIPT | ADJUSTMENT | PRODUCTION_ISSUE."""


def _column_name(spec: str) -> str:
    return spec.split(" ", 1)[0]


def view_columns(view: str) -> list[str]:
    """Bare column names documented for a view (used by tests to check parity)."""
    return [_column_name(c) for c in VIEW_CATALOG[view][1]]


def catalog_text() -> str:
    """Compact schema description for SQL prompts."""
    lines = ["Views (preferred):"]
    for name, (desc, cols) in VIEW_CATALOG.items():
        lines.append(f"- {name}: {desc}\n    columns: {', '.join(cols)}")
    lines.append("Base tables (use only when no view fits):")
    for name in BASE_TABLES:
        table = Base.metadata.tables[name]
        cols = ", ".join(c.name for c in table.columns)
        lines.append(f"- {name}({cols})")
    lines.append(GLOSSARY)
    return "\n".join(lines)
