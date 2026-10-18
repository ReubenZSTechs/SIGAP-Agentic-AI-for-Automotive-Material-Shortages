"""Chatbot data layer: semantic views, curated tools, SQL guard and read-only executor."""
import pytest
from sqlalchemy import inspect, text

from app.chatbot.schema_catalog import ALLOWED_RELATIONS, VIEW_CATALOG, view_columns
from app.services import inventory_service
from configs.tools.curated import CURATED, resolve_materials
from configs.tools.registry import run_curated
from configs.tools.sql_executor import SqlExecutionError, run_select
from configs.tools.sql_guard import SqlGuardError, validate_sql
from tests.test_flow_e2e import _schedule_two_days


def _views_by_sku(engine) -> dict:
    with engine.connect() as c:
        rows = c.execute(text("SELECT * FROM chat_inventory_status_v")).mappings().all()
    return {r["sku"]: r for r in rows}


def _assert_parity(db, engine):
    db.expire_all()
    view = _views_by_sku(engine)
    service = inventory_service.list_inventory(db)
    assert len(view) == len(service)
    for row in service:
        v = view[row["sku"]]
        assert v["available"] == pytest.approx(row["available"])
        assert v["on_order"] == pytest.approx(row["on_order"])
        assert v["status"] == row["status"].value


def test_view_columns_match_catalog(engine):
    insp = inspect(engine)
    for view in VIEW_CATALOG:
        assert [c["name"] for c in insp.get_columns(view)] == view_columns(view)


def test_inventory_view_matches_service_before_and_after_planning(client, db, engine, seeded):
    _assert_parity(db, engine)
    run = _schedule_two_days(client, seeded["BIKE"])
    _assert_parity(db, engine)
    lines = {l["sku"]: l["id"] for l in run["lines"]}
    client.put(f"/api/v1/planning/lines/{lines['RM-RUB-01']}/selection",
               json={"supplier_id": seeded["KARET"], "order_qty": 100})
    client.put(f"/api/v1/planning/lines/{lines['RM-SBR-01']}/selection",
               json={"supplier_id": seeded["CIPTA"], "order_qty": 50})
    client.put(f"/api/v1/planning/lines/{lines['RM-STEEL-01']}/selection",
               json={"supplier_id": seeded["CIPTA"], "order_qty": 100})
    client.put(f"/api/v1/planning/lines/{lines['RM-PDL-01']}/selection",
               json={"supplier_id": seeded["INDUSTRI"], "order_qty": 50})
    assert client.post(f"/api/v1/planning/runs/{run['id']}/purchase-orders").status_code == 201
    _assert_parity(db, engine)
    assert _views_by_sku(engine)["RM-RUB-01"]["on_order"] == 100
    ev = run_curated("get_open_purchase_orders", {"supplier": "cipta"}, "", "E1", 200)
    assert ev["meta"]["open_po_count"] == 1 and ev["meta"]["po_totals"] == {ev["rows"][0]["po_number"]: 3400000}


def test_material_suppliers_tool_flags_cheapest_and_fastest(seeded):
    ev = run_curated("get_material_suppliers", {"material": "pedal"}, "suppliers", "E1", 200)
    assert ev["error"] is None and ev["row_count"] == 3
    by_name = {r["supplier_name"]: r for r in ev["rows"]}
    assert by_name["CV Makmur Bersama"]["is_cheapest"] and by_name["CV Makmur Bersama"]["unit_price"] == 42500
    assert by_name["PT Industri Lokal"]["is_fastest"] and by_name["PT Industri Lokal"]["lead_time_days"] == 2


def test_material_suppliers_view_agrees_with_tool(engine, seeded):
    ev = run_curated("get_material_suppliers", {"material": "RM-PDL-01"}, "", "E1", 200)
    with engine.connect() as c:
        view = c.execute(text("SELECT supplier_name, is_cheapest, is_fastest FROM chat_material_suppliers_v "
                              "WHERE material_sku = 'RM-PDL-01'")).mappings().all()
    assert {(v["supplier_name"], v["is_cheapest"], v["is_fastest"]) for v in view} == \
           {(r["supplier_name"], r["is_cheapest"], r["is_fastest"]) for r in ev["rows"]}


def test_critical_items_tool_after_scheduling(client, seeded):
    _schedule_two_days(client, seeded["BIKE"])
    ev = run_curated("get_critical_items", {"include_warning": True}, "", "E1", 200)
    status = {r["sku"]: r["status"] for r in ev["rows"]}
    assert status == {"RM-RUB-01": "CRITICAL", "RM-SBR-01": "CRITICAL",
                      "RM-STEEL-01": "WARNING", "RM-PDL-01": "WARNING"}
    assert list(status)[:2] == ["RM-RUB-01", "RM-SBR-01"]


def test_resolve_materials_is_fuzzy(db, seeded):
    assert [m.sku for m in resolve_materials(db, "rm-pdl-01")] == ["RM-PDL-01"]
    assert [m.sku for m in resolve_materials(db, "Ban Luar")] == ["RM-RUB-01"]
    assert [m.sku for m in resolve_materials(db, "Pedall Sepeda")] == ["RM-PDL-01"]


@pytest.mark.parametrize("tool", sorted(CURATED))
def test_every_curated_tool_runs_on_seed(tool, client, seeded):
    _schedule_two_days(client, seeded["BIKE"])
    args = {"get_material_suppliers": {"material": "Ban Luar Karet"}, "find_materials": {"query": "ban"},
            "get_bom": {"product": "Sepeda Gunung", "qty": 50}}.get(tool, {})
    ev = run_curated(tool, args, "", "E1", 200)
    assert ev["error"] is None
    assert ev["row_count"] > 0 or tool == "get_open_purchase_orders"


def test_bom_tool_scales_quantities(seeded):
    ev = run_curated("get_bom", {"product": "FG-BIKE-01", "qty": 50}, "", "E1", 200)
    rub = next(r for r in ev["rows"] if r["sku"] == "RM-RUB-01")
    assert rub["required_qty"] == 100


@pytest.mark.parametrize("sql", [
    "DELETE FROM materials", "UPDATE inventory SET on_hand = 0", "SELECT 1; SELECT 2",
    "SELECT pg_sleep(5)", "SELECT * FROM pg_roles", "SELECT * FROM information_schema.tables",
    "SELECT * INTO hack FROM materials", "SELECT * FROM materials FOR UPDATE", "DROP TABLE materials",
    "SELECT * FROM checkpoints",
])
def test_sql_guard_rejects_unsafe(sql):
    with pytest.raises(SqlGuardError):
        validate_sql(sql, ALLOWED_RELATIONS, 200)


def test_sql_guard_enforces_limit_and_allows_ctes():
    assert validate_sql("SELECT sku FROM chat_inventory_status_v", ALLOWED_RELATIONS, 50).endswith("LIMIT 50")
    assert validate_sql("SELECT sku FROM materials LIMIT 10", ALLOWED_RELATIONS, 50).endswith("LIMIT 10")
    assert validate_sql("SELECT sku FROM materials LIMIT 999", ALLOWED_RELATIONS, 50).endswith("LIMIT 50")
    sql = "WITH c AS (SELECT * FROM chat_inventory_status_v) SELECT status, COUNT(*) FROM c GROUP BY status"
    assert "LIMIT 200" in validate_sql(sql, ALLOWED_RELATIONS, 200)


def test_executor_reads_and_refuses_writes(seeded):
    cols, rows = run_select("SELECT sku, name FROM materials WHERE name ILIKE '%pedal%' LIMIT 5", 5000)
    assert cols == ["sku", "name"] and rows[0]["sku"] == "RM-PDL-01"
    with pytest.raises(SqlExecutionError, match="read-only"):
        run_select("UPDATE inventory SET on_hand = 0", 5000)
