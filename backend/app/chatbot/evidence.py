"""Evidence: tool results the answer must be grounded in, plus table rendering."""
import enum
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, TypedDict


class Evidence(TypedDict):
    """One tool result. JSON-serializable so it can live in the LangGraph checkpoint."""
    id: str
    tool: str
    args: dict
    purpose: str
    columns: list[str]
    rows: list[dict]
    row_count: int
    truncated: bool
    meta: dict
    sql: str | None
    error: str | None


def to_jsonable(value: Any) -> Any:
    """Converts DB/ORM values to plain JSON types (floats without spurious decimals)."""
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        return int(value) if value.is_integer() else round(value, 6)
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def make_evidence(eid: str, tool: str, args: dict, purpose: str, rows: list[dict], *,
                  row_limit: int, meta: dict | None = None, sql: str | None = None,
                  error: str | None = None, columns: list[str] | None = None) -> Evidence:
    """Builds an `Evidence`, normalizing values and capping rows at `row_limit`."""
    rows = [to_jsonable(r) for r in rows]
    cols = columns or (list(rows[0].keys()) if rows else [])
    return Evidence(id=eid, tool=tool, args={k: v for k, v in args.items() if v is not None},
                    purpose=purpose, columns=cols, rows=rows[:row_limit], row_count=len(rows),
                    truncated=len(rows) > row_limit, meta=to_jsonable(meta or {}), sql=sql, error=error)


def evidence_prompt(evidence: list[Evidence], max_rows: int) -> str:
    """Serializes evidence for prompts; rows beyond `max_rows` are summarized, not shown."""
    blocks = []
    for ev in evidence:
        head = {"id": ev["id"], "tool": ev["tool"], "args": ev["args"], "purpose": ev["purpose"],
                "row_count": ev["row_count"], "columns": ev["columns"]}
        if ev["meta"]:
            head["meta"] = ev["meta"]
        if ev["error"]:
            head["error"] = ev["error"]
        if ev["sql"]:
            head["sql"] = ev["sql"]
        shown = ev["rows"][:max_rows]
        if len(ev["rows"]) > len(shown) or ev["truncated"]:
            head["note"] = f"only the first {len(shown)} of {ev['row_count']} rows are shown"
        blocks.append(json.dumps({**head, "rows": shown}, ensure_ascii=False))
    return "\n".join(blocks) if blocks else "(no evidence)"


_LABELS = {
    "id": {"sku": "SKU", "name": "Nama", "material_name": "Material", "material_sku": "SKU",
           "category": "Kategori", "uom": "Satuan", "on_hand": "Stok Fisik", "allocated": "Terkunci",
           "available": "Tersedia", "safety_stock": "Batas Aman", "on_order": "Dipesan",
           "shortfall": "Defisit", "status": "Status", "supplier_name": "Supplier",
           "supplier_code": "Kode Supplier", "unit_price": "Harga Satuan", "lead_time_days": "Lead Time (hari)",
           "moq": "MOQ", "is_cheapest": "Termurah", "is_fastest": "Tercepat", "po_number": "No. PO",
           "po_status": "Status PO", "qty_ordered": "Qty Pesan", "qty_received": "Qty Diterima",
           "qty_remaining": "Sisa", "line_total": "Total Baris", "product_name": "Produk",
           "production_date": "Tanggal Produksi", "target_qty": "Target", "batch_code": "Batch",
           "gross_requirement": "Kebutuhan Kotor", "qty_per_parent": "Qty per Induk",
           "required_qty": "Qty Dibutuhkan", "level": "Level", "parent_name": "Induk", "order_qty": "Qty Beli", "cost": "Biaya",
           "total_cost": "Total Biaya", "difference_vs_cheapest": "Selisih vs Termurah",
           "arrival_date": "Perkiraan Tiba", "late": "Terlambat", "payment_term_days": "Termin (hari)",
           "is_preferred": "Utama", "selling_price": "Harga Jual", "bom_item_count": "Komponen BOM",
           "is_active": "Aktif", "specification": "Spesifikasi", "supplier_count": "Jumlah Supplier",
           "cheapest_supplier": "Supplier Termurah", "cheapest_cost": "Biaya Termurah",
           "most_expensive_supplier": "Supplier Termahal", "most_expensive_cost": "Biaya Termahal",
           "cost_difference": "Selisih Biaya"},
    "en": {"sku": "SKU", "name": "Name", "material_name": "Material", "supplier_name": "Supplier",
           "required_qty": "Required Qty", "order_qty": "Order Qty", "unit_price": "Unit Price", "cost": "Cost",
           "total_cost": "Total Cost", "difference_vs_cheapest": "Diff. vs Cheapest", "arrival_date": "Arrival",
           "lead_time_days": "Lead Time (days)", "late": "Late", "cheapest_supplier": "Cheapest Supplier",
           "cheapest_cost": "Cheapest Cost", "most_expensive_supplier": "Most Expensive Supplier",
           "most_expensive_cost": "Most Expensive Cost", "cost_difference": "Cost Difference",
           "payment_term_days": "Payment Term (days)", "is_preferred": "Preferred", "uom": "Unit",
           "on_hand": "On Hand", "available": "Available", "safety_stock": "Safety Stock", "status": "Status",
           "parent_name": "Parent", "selling_price": "Selling Price", "bom_item_count": "BOM Items"},
}


def _label(column: str, language: str) -> str:
    return _LABELS.get(language, {}).get(column) or column.replace("_", " ").capitalize()


def _cell(value: Any, language: str) -> str:
    if value is None:
        return "–"
    if isinstance(value, bool):
        return ("Ya" if value else "Tidak") if language == "id" else ("Yes" if value else "No")
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".") if language == "id" else f"{value:,}"
    if isinstance(value, float):
        text = f"{value:,.2f}".rstrip("0").rstrip(".")
        return text.translate(str.maketrans(",.", ".,")) if language == "id" else text
    return str(value)


# Code column -> the name column that replaces it in chat tables (users read names, not SKU/supplier codes).
_CODE_TO_NAME = {"sku": "name", "material_sku": "material_name", "supplier_code": "supplier_name",
                 "parent_sku": "parent_name"}


def names_instead_of_codes(cols: list[str], available: list[str]) -> list[str]:
    """Drops a code column when its name column is available, and puts the name where the code was."""
    out = []
    for c in cols:
        if c in _CODE_TO_NAME and _CODE_TO_NAME[c] in available:
            c = _CODE_TO_NAME[c]
        if c not in out:
            out.append(c)
    return out


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _norm(v) -> str:
    return str(v).strip().casefold() if v is not None else ""


def _matches(row: dict, f: dict) -> bool:
    cell, op = row.get(f["column"]), f["op"]
    if op in ("in", "not_in"):
        hit = _norm(cell) in {_norm(x) for x in (f.get("values") or [])}
        return hit if op == "in" else not hit
    target = f.get("value")
    if op in ("eq", "ne"):
        a, b = _num(cell), _num(target)
        same = (a == b) if a is not None and b is not None else _norm(cell) == _norm(target)
        return same if op == "eq" else not same
    if op == "contains":
        return _norm(target) in _norm(cell)
    a, b = _num(cell), _num(target)
    if a is None or b is None:
        return False
    return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]


def filter_rows(ev: Evidence, filters: list[dict] | None) -> list[dict]:
    """Rows of `ev` matching ALL filters (deterministic; filters on unknown columns are ignored)."""
    valid = [f for f in (filters or []) if f.get("column") in ev["columns"] and f.get("op")]
    return [r for r in ev["rows"] if all(_matches(r, f) for f in valid)]


def filtered_evidence(ev: Evidence, filters: list[dict] | None) -> Evidence:
    """Copy of `ev` restricted to the rows a table block shows (used for grounding checks)."""
    rows = filter_rows(ev, filters)
    return {**ev, "id": f"{ev['id']}*", "rows": rows, "row_count": len(rows), "truncated": False}


def render_table(ev: Evidence, columns: list[str] | None, language: str,
                 title: str | None = None, filters: list[dict] | None = None) -> dict:
    """Frontend table block built from real evidence rows (never from model text).

    `filters` (from the synthesizer) select WHICH rows are shown, e.g. only non-critical items; the
    rows themselves always come from the evidence."""
    cols = [c for c in (columns or ev["columns"]) if c in ev["columns"]] or ev["columns"]
    cols = names_instead_of_codes(cols, ev["columns"])
    block = {"type": "table", "columns": [_label(c, language) for c in cols],
             "rows": [[_cell(r.get(c), language) for c in cols] for r in filter_rows(ev, filters)],
             "evidence_id": ev["id"]}
    if title:
        block["title"] = title
    return block
