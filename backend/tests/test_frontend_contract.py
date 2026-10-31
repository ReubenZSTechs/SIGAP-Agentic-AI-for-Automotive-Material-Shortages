"""Kontrak yang dibutuhkan frontend React (Frontend Plan §0.3)."""
from tests.test_flow_e2e import API, _schedule_two_days


def test_cors_preflight_allows_any_origin(client):
    # CORS_ORIGINS="*" (default): the frontend can be served from any host (Vite, SAP BTP route, ...)
    r = client.options(f"{API}/materials", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
    for origin in ("http://localhost:5173", "https://mrp-frontend-suppliers.cfapps.ap10.hana.ondemand.com"):
        r = client.get(f"{API}/materials", headers={"Origin": origin})
        assert r.headers["access-control-allow-origin"] == "*"


def test_bom_tree_nodes_carry_bom_item_id(client, seeded):
    tree = client.get(f"{API}/bom/{seeded['BIKE']}/tree").json()
    assert tree["bom_item_id"] is None                       # root
    ids = []

    def walk(n):
        for c in n["children"]:
            assert isinstance(c["bom_item_id"], int)
            ids.append(c["bom_item_id"])
            walk(c)
    walk(tree)
    assert len(ids) == len(set(ids)) == 4 + 15                # 4 sub-assembly + 15 komponen BUY
    # id dapat dipakai untuk PATCH/DELETE node
    leaf = tree["children"][0]["children"][0]
    r = client.patch(f"{API}/bom/items/{leaf['bom_item_id']}", json={"qty_per_parent": 2})
    assert r.status_code == 200 and r.json()["qty_per_parent"] == 2


def test_po_items_expose_name_sku_uom_and_run_filter(client, seeded):
    run = _schedule_two_days(client, seeded["BIKE"])
    assert client.get(f"{API}/purchase-orders", params={"planning_run_id": run["id"]}).json() == []
    client.post(f"{API}/planning/runs/{run['id']}/sourcing/auto-select", json={})
    pos = client.post(f"{API}/planning/runs/{run['id']}/purchase-orders").json()
    item = pos[0]["items"][0]
    assert {"sku", "name", "uom", "qty_ordered", "qty_received", "unit_price", "line_total"} <= item.keys()
    listed = client.get(f"{API}/purchase-orders", params={"planning_run_id": run["id"]}).json()
    assert len(listed) == len(pos) and all(p["supplier_name"] for p in listed)
    assert client.get(f"{API}/purchase-orders", params={"planning_run_id": 9999}).json() == []


def test_line_and_inventory_fields_used_by_ui(client, seeded):
    run = _schedule_two_days(client, seeded["BIKE"])
    line = run["lines"][0]
    assert {"sku", "material_name", "uom", "selected_supplier_name", "needed_by", "on_order"} <= line.keys()
    inv = client.get(f"{API}/inventory").json()[0]
    assert {"sku", "name", "uom", "on_hand", "allocated", "available", "safety_stock", "status"} <= inv.keys()
    sch = client.get(f"{API}/schedules").json()[0]
    assert "product_name" in sch
