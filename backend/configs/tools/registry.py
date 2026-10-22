"""Tool catalog shown to the retrieval planner and the dispatcher that runs planned calls.

`TOOL_CATALOG` / `CURATED` are READ-ONLY (read-only session). Write tools for PO automation and the
supplier Telegram agent live in `configs.tools.po_actions.WRITE_TOOLS` and are never offered to the
retrieval planner; only deterministic workflow nodes call them.
"""
from app.chatbot import tracing
from app.chatbot.db import chat_session
from app.chatbot.evidence import Evidence, make_evidence
from configs.tools.curated import CURATED

TOOL_CATALOG: dict[str, tuple[str, str]] = {
    "get_stock_summary": ("category?, status?",
                          "Current stock for every item: on_hand, allocated, available, safety_stock, "
                          "on_order, shortfall, status. Filter by category (FINISHED|SUB_PART|PURCHASED) "
                          "and/or status (CRITICAL|WARNING|SAFE)."),
    "get_critical_items": ("include_warning?",
                           "Items whose status is CRITICAL (available <= 0); with include_warning=true "
                           "also WARNING (available below safety stock). Sorted most severe first."),
    "find_materials": ("query", "Look up items by SKU or approximate name; use to disambiguate names."),
    "get_material_suppliers": ("material",
                               "All suppliers of a material (SKU or name, fuzzy): unit_price, "
                               "lead_time_days, moq, payment terms, is_preferred, is_cheapest, is_fastest."),
    "list_suppliers": ("query?", "All suppliers (optionally filtered by code/name) with payment terms "
                                 "and the materials each supplies."),
    "get_open_purchase_orders": ("supplier?, material?",
                                 "Open purchase order lines (DRAFT, PENDING_APPROVAL, APPROVED, ISSUED, "
                                 "PARTIALLY_RECEIVED) with ordered/received/remaining qty and amounts."),
    "get_latest_planning_run": ("", "Most recent MRP planning run: per-material gross requirement, "
                                    "shortfall, status, selected supplier, plus run date range and staleness."),
    "list_products": ("query?", "All finished products (Produk Final) with selling price, specification, active "
                                "flag and number of BOM components; optional filter by SKU/name. Use this to "
                                "list or count finished products (they have no stock rows)."),
    "get_bom": ("product, qty?", "Multi-level bill of materials of a finished product or sub-part, with "
                                 "required quantity of every component for qty units."),
    "get_production_schedules": ("date_from?, date_to?, schedule_status?",
                                 "Production batches (MPS): product, line, date, target qty, status."),
    "get_po_supplier_status": ("query?, supplier?",
                               "Supplier confirmation of purchase orders via the Telegram agent: confirmation "
                               "status (PENDING/CONFIRMED/DECLINED/CANCEL_PENDING/REVISION_PENDING), promised "
                               "delivery date, last conversation, pending revision requests. query = PO number/id; "
                               "without it, all open POs."),
    "query_database": ("question",
                       "Fallback text-to-SQL agent over read-only views/tables for anything the tools "
                       "above cannot answer (aggregations, rankings, stock movement history, joins)."),
}


def catalog_text() -> str:
    """Tool list for the planner prompt."""
    return "\n".join(f"- {name}({args}): {desc}" for name, (args, desc) in TOOL_CATALOG.items())


def run_curated(tool: str, args: dict, purpose: str, eid: str, row_limit: int) -> Evidence:
    """Runs a curated tool in a read-only session and wraps the result as evidence (traced in `tool_runs`)."""
    with tracing.record_tool(tool, "read", args) as run, chat_session() as db:
        try:
            rows, meta = CURATED[tool](db, **args)
        except Exception as e:  # noqa: BLE001
            run.fail(f"{type(e).__name__}: {e}")
            return make_evidence(eid, tool, args, purpose, [], row_limit=row_limit,
                                 error=f"{type(e).__name__}: {e}")
        run.done(rows)
    return make_evidence(eid, tool, args, purpose, rows, row_limit=row_limit, meta=meta)


def run_query_database(sql_graph, args: dict, purpose: str, eid: str, language: str,
                       row_limit: int) -> Evidence:
    """Runs the query_database subgraph and wraps its result (or failure) as evidence."""
    question = args.get("question") or purpose
    try:
        out = sql_graph.invoke({"question": question, "language": language})
    except Exception as e:  # noqa: BLE001
        return make_evidence(eid, "query_database", args, purpose, [], row_limit=row_limit,
                             error=f"{type(e).__name__}: {e}")
    meta = {"attempts": out.get("attempts", 0)}
    return make_evidence(eid, "query_database", args, purpose, out.get("rows") or [],
                         row_limit=row_limit, meta=meta, sql=out.get("sql"), error=out.get("error"),
                         columns=out.get("columns"))
