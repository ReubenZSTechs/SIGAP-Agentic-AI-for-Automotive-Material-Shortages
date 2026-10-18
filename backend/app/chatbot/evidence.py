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
           "required_qty": "Qty Dibutuhkan", "level": "Level"},
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


def render_table(ev: Evidence, columns: list[str] | None, language: str,
                 title: str | None = None) -> dict:
    """Frontend table block built from real evidence rows (never from model text)."""
    cols = [c for c in (columns or ev["columns"]) if c in ev["columns"]] or ev["columns"]
    block = {"type": "table", "columns": [_label(c, language) for c in cols],
             "rows": [[_cell(r.get(c), language) for c in cols] for r in ev["rows"]],
             "evidence_id": ev["id"]}
    if title:
        block["title"] = title
    return block
