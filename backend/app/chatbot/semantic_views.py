"""Semantic layer: read-only Postgres views that encode MRP business rules for the chatbot.

The views are (re)created after every `Base.metadata.create_all` and dropped before
`drop_all`, so they stay in sync with the ORM schema everywhere (app startup, seed, tests).
"""
from sqlalchemy import event, text

from app.database import Base

OPEN_PO_STATUSES = ("DRAFT", "PENDING_APPROVAL", "APPROVED", "ISSUED", "PARTIALLY_RECEIVED")


def _counted_predicate() -> str:
    """SQL form of `planning_service.COUNTED` (which PO statuses count as on-order)."""
    from app.services.planning_service import COUNTED
    parts = []
    for source, statuses in COUNTED.items():
        values = ", ".join(f"'{s.name}'" for s in statuses)
        parts.append(f"(po.source = '{source.name}' AND po.status IN ({values}))")
    return " OR ".join(parts)


def view_definitions() -> dict[str, str]:
    """View name -> SELECT body. Status rules mirror `planning_service.classify`."""
    open_statuses = ", ".join(f"'{s}'" for s in OPEN_PO_STATUSES)
    return {
        "chat_inventory_status_v": f"""
            WITH oo AS (
                SELECT pi.material_id, SUM(pi.qty_ordered - pi.qty_received) AS on_order
                FROM po_items pi JOIN purchase_orders po ON po.id = pi.po_id
                WHERE {_counted_predicate()}
                GROUP BY pi.material_id
            )
            SELECT m.id AS material_id, m.sku, m.name, m.category, m.uom, m.is_active,
                   i.on_hand, i.allocated, i.on_hand - i.allocated AS available, i.safety_stock,
                   COALESCE(oo.on_order, 0) AS on_order,
                   GREATEST(0, i.safety_stock - ((i.on_hand - i.allocated) + COALESCE(oo.on_order, 0)))
                       AS shortfall,
                   CASE WHEN i.on_hand - i.allocated <= 0 THEN 'CRITICAL'
                        WHEN i.on_hand - i.allocated < i.safety_stock THEN 'WARNING'
                        ELSE 'SAFE' END AS status
            FROM inventory i
            JOIN materials m ON m.id = i.material_id
            LEFT JOIN oo ON oo.material_id = i.material_id""",
        "chat_material_suppliers_v": """
            SELECT m.sku AS material_sku, m.name AS material_name,
                   s.code AS supplier_code, s.name AS supplier_name,
                   ms.unit_price, ms.lead_time_days, ms.moq, ms.is_preferred,
                   ms.is_active, s.is_active AS supplier_is_active, s.payment_term_days,
                   COALESCE(ms.is_active AND ms.unit_price = MIN(ms.unit_price)
                       FILTER (WHERE ms.is_active) OVER (PARTITION BY ms.material_id), false) AS is_cheapest,
                   COALESCE(ms.is_active AND ms.lead_time_days = MIN(ms.lead_time_days)
                       FILTER (WHERE ms.is_active) OVER (PARTITION BY ms.material_id), false) AS is_fastest
            FROM material_suppliers ms
            JOIN materials m ON m.id = ms.material_id
            JOIN suppliers s ON s.id = ms.supplier_id""",
        "chat_purchase_order_items_v": f"""
            SELECT po.po_number, po.status AS po_status, po.source AS po_source, po.po_date,
                   po.status IN ({open_statuses}) AS is_open,
                   po.total_amount AS po_total_amount, po.planning_run_id,
                   s.code AS supplier_code, s.name AS supplier_name,
                   m.sku, m.name AS material_name, m.uom,
                   pi.qty_ordered, pi.qty_received, pi.qty_ordered - pi.qty_received AS qty_remaining,
                   pi.unit_price, pi.line_total, pi.needed_by_date
            FROM po_items pi
            JOIN purchase_orders po ON po.id = pi.po_id
            JOIN suppliers s ON s.id = po.supplier_id
            JOIN materials m ON m.id = pi.material_id""",
        "chat_latest_planning_lines_v": """
            SELECT r.id AS run_id, r.date_from AS run_date_from, r.date_to AS run_date_to,
                   r.status AS run_status, r.is_stale AS run_is_stale, r.created_at AS run_created_at,
                   m.sku, m.name AS material_name, m.uom,
                   l.gross_requirement, l.on_hand, l.allocated, l.available, l.on_order,
                   l.safety_stock, l.shortfall, l.status, l.needed_by,
                   s.name AS selected_supplier_name, l.order_qty, l.unit_price, l.lead_time_days
            FROM planning_lines l
            JOIN planning_runs r ON r.id = l.run_id
            JOIN materials m ON m.id = l.material_id
            LEFT JOIN suppliers s ON s.id = l.selected_supplier_id
            WHERE r.id = (SELECT MAX(id) FROM planning_runs)""",
        "chat_schedules_v": """
            SELECT sc.batch_code, m.sku AS product_sku, m.name AS product_name,
                   pl.code AS line_code, pl.name AS line_name,
                   sc.production_date, sc.target_qty, sc.status, sc.started_at, sc.completed_at
            FROM schedules sc
            JOIN materials m ON m.id = sc.product_id
            JOIN production_lines pl ON pl.id = sc.production_line_id""",
        "chat_bom_v": """
            SELECT p.sku AS parent_sku, p.name AS parent_name, p.category AS parent_category,
                   c.sku AS child_sku, c.name AS child_name, c.category AS child_category,
                   c.uom AS child_uom, b.qty_per_parent
            FROM bom_items b
            JOIN materials p ON p.id = b.parent_id
            JOIN materials c ON c.id = b.child_id""",
    }


def drop_views(connection) -> None:
    """Drops every chatbot view (safe when they do not exist)."""
    for name in view_definitions():
        connection.execute(text(f"DROP VIEW IF EXISTS {name} CASCADE"))


def create_views(connection) -> None:
    """Recreates every chatbot view from the current definitions."""
    drop_views(connection)
    for name, body in view_definitions().items():
        connection.execute(text(f"CREATE VIEW {name} AS {body}"))


@event.listens_for(Base.metadata, "after_create")
def _after_create(_target, connection, **_kw):
    create_views(connection)


@event.listens_for(Base.metadata, "before_drop")
def _before_drop(_target, connection, **_kw):
    drop_views(connection)
