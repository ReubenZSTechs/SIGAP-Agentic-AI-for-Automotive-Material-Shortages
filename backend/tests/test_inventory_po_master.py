import pytest

from app.core.exceptions import AppError
from tests.test_flow_e2e import API, _schedule_two_days


def _issued_po(client, seeded):
    run = _schedule_two_days(client, seeded["BIKE"])
    client.post(f"{API}/planning/runs/{run['id']}/sourcing/auto-select", json={})
    pos = client.post(f"{API}/planning/runs/{run['id']}/purchase-orders").json()
    po = next(p for p in pos if p["supplier_name"] == "PT Karet Nusantara")
    client.patch(f"{API}/purchase-orders/{po['id']}/status", json={"status": "ISSUED"})
    return po, client.get(f"{API}/purchase-orders/{po['id']}").json()


def test_receipt_rejects_over_receipt_and_is_atomic(client, seeded):
    po, full = _issued_po(client, seeded)
    item = full["items"][0]
    r = client.post(f"{API}/purchase-orders/{po['id']}/receipts",
                    json={"items": [{"po_item_id": item["id"], "qty_received": item["qty_ordered"] + 1}]})
    assert r.status_code == 400
    # duplikat item di payload digabung lalu divalidasi -> tetap ditolak
    half = item["qty_ordered"] * 0.6
    r = client.post(f"{API}/purchase-orders/{po['id']}/receipts",
                    json={"items": [{"po_item_id": item["id"], "qty_received": half},
                                    {"po_item_id": item["id"], "qty_received": half}]})
    assert r.status_code == 400
    inv = {i["sku"]: i for i in client.get(f"{API}/inventory").json()}
    assert inv["RM-RUB-01"]["on_hand"] == 80                         # tidak ada perubahan stok
    # po_item bukan milik PO
    assert client.post(f"{API}/purchase-orders/{po['id']}/receipts",
                       json={"items": [{"po_item_id": 99999, "qty_received": 1}]}).status_code == 400


def test_partial_receipt_then_complete(client, seeded):
    po, full = _issued_po(client, seeded)
    item = full["items"][0]
    r = client.post(f"{API}/purchase-orders/{po['id']}/receipts",
                    json={"items": [{"po_item_id": item["id"], "qty_received": 20}]})
    assert r.json()["po_status"] == "PARTIALLY_RECEIVED"
    assert r.json()["changes"][0]["old_on_hand"] == 80 and r.json()["changes"][0]["new_on_hand"] == 100
    r = client.post(f"{API}/purchase-orders/{po['id']}/receipts",
                    json={"items": [{"po_item_id": item["id"], "qty_received": item["qty_ordered"] - 20}]})
    assert r.json()["po_status"] == "RECEIVED"
    # PO selesai tidak bisa menerima lagi
    assert client.post(f"{API}/purchase-orders/{po['id']}/receipts",
                       json={"items": [{"po_item_id": item["id"], "qty_received": 1}]}).status_code == 409


def test_receipt_requires_issued_and_status_transitions(client, seeded):
    run = _schedule_two_days(client, seeded["BIKE"])
    client.post(f"{API}/planning/runs/{run['id']}/sourcing/auto-select", json={})
    po = client.post(f"{API}/planning/runs/{run['id']}/purchase-orders").json()[0]
    item = po["items"][0]
    rcpt = {"items": [{"po_item_id": item["id"], "qty_received": 1}]}
    assert client.post(f"{API}/purchase-orders/{po['id']}/receipts", json=rcpt).status_code == 409   # DRAFT
    assert client.patch(f"{API}/purchase-orders/{po['id']}/status", json={"status": "RECEIVED"}).status_code == 422
    assert client.patch(f"{API}/purchase-orders/{po['id']}/status", json={"status": "CANCELLED"}).status_code == 200
    assert client.patch(f"{API}/purchase-orders/{po['id']}/status", json={"status": "ISSUED"}).status_code == 409
    assert client.get(f"{API}/purchase-orders", params={"status": "CANCELLED"}).json()[0]["id"] == po["id"]
    assert client.get(f"{API}/purchase-orders/9999").status_code == 404


def test_inventory_adjustment_logged(client, seeded):
    mid = seeded["materials"]["RM-PDL-01"]
    r = client.put(f"{API}/inventory/{mid}", json={"on_hand": 150, "safety_stock": 40})
    assert r.status_code == 200 and r.json()["on_hand"] == 150 and r.json()["safety_stock"] == 40
    mv = client.get(f"{API}/stock-movements", params={"material_id": mid}).json()
    assert len(mv) == 1 and mv[0]["type"] == "ADJUSTMENT" and mv[0]["qty"] == 30


def test_master_crud_and_material_supplier_relation(client, seeded):
    r = client.post(f"{API}/materials", json={"sku": "RM-NEW-01", "name": "Baru", "uom": "kg"})
    assert r.status_code == 201 and r.json()["procurement_type"] == "BUY" and r.json()["category"] == "PURCHASED"
    assert client.post(f"{API}/materials", json={"sku": "RM-NEW-01", "name": "X", "uom": "kg"}).status_code == 409
    mid = r.json()["id"]
    s = client.post(f"{API}/suppliers", json={"code": "SUP-X", "name": "PT X"})
    assert s.status_code == 201
    assert client.post(f"{API}/suppliers", json={"code": "SUP-X", "name": "dup"}).status_code == 409
    sid = s.json()["id"]

    link = client.post(f"{API}/materials/{mid}/suppliers",
                       json={"supplier_id": sid, "unit_price": 1000, "lead_time_days": 2})
    assert link.status_code == 201 and link.json()["moq"] == 1
    assert client.post(f"{API}/materials/{mid}/suppliers",
                       json={"supplier_id": sid, "unit_price": 1, "lead_time_days": 1}).status_code == 409
    assert client.post(f"{API}/materials/{mid}/suppliers",
                       json={"supplier_id": 9999, "unit_price": 1, "lead_time_days": 1}).status_code == 404
    assert client.patch(f"{API}/materials/{mid}/suppliers/{sid}", json={"unit_price": 900}).json()["unit_price"] == 900

    pdl = seeded["materials"]["RM-PDL-01"]
    links = client.get(f"{API}/materials/{pdl}/suppliers").json()
    assert len(links) == 3
    assert [l["supplier_name"] for l in links if l["is_cheapest"]] == ["CV Makmur Bersama"]
    assert [l["supplier_name"] for l in links if l["is_fastest"]] == ["PT Industri Lokal"]

    assert client.delete(f"{API}/suppliers/{sid}").status_code == 409     # masih punya relasi
    assert client.delete(f"{API}/materials/{mid}/suppliers/{sid}").status_code == 204
    assert client.delete(f"{API}/suppliers/{sid}").status_code == 204
    assert client.delete(f"{API}/materials/{mid}").status_code == 204
    assert client.get(f"{API}/materials/{mid}").status_code == 404
    assert client.delete(f"{API}/materials/{pdl}").status_code == 409     # dipakai BOM

    flt = client.get(f"{API}/materials", params={"category": "SUB_PART"}).json()
    assert len(flt) == 4 and len(client.get(f"{API}/materials", params={"category": "FINISHED"}).json()) == 1
    assert client.get(f"{API}/materials", params={"q": "pedal"}).json()[0]["sku"] == "RM-PDL-01"


def test_schedule_validation_and_soft_delete(client, seeded):
    bad = client.post(f"{API}/schedules", json={"product_id": seeded["materials"]["RM-PDL-01"],
                                                "production_date": "2026-10-12", "target_qty": 5})
    assert bad.status_code == 422
    sub = client.post(f"{API}/schedules", json={"product_id": seeded["materials"]["SA-FRAME-01"],
                                                "production_date": "2026-10-12", "target_qty": 5})
    assert sub.status_code == 422                                       # sub-part tidak dijadwalkan
    assert client.post(f"{API}/schedules", json={"product_id": seeded["BIKE"],
                                                 "production_date": "2026-10-12", "target_qty": 0}).status_code == 422
    s = client.post(f"{API}/schedules", json={"product_id": seeded["BIKE"],
                                              "production_date": "2026-10-12", "target_qty": 5}).json()
    assert client.patch(f"{API}/schedules/{s['id']}", json={"target_qty": 8}).json()["target_qty"] == 8
    assert client.delete(f"{API}/schedules/{s['id']}").status_code == 204
    assert client.get(f"{API}/schedules", params={"status": "CANCELLED"}).json()[0]["id"] == s["id"]
    # jadwal CANCELLED tidak ikut planning
    assert client.post(f"{API}/planning/runs",
                       json={"date_from": "2026-10-12", "date_to": "2026-10-12"}).status_code == 400
    assert client.post(f"{API}/planning/runs",
                       json={"date_from": "2026-10-13", "date_to": "2026-10-12"}).status_code == 422
