"""E2E Phase 0 -> 5 persis mengikuti spesifikasi."""
API = "/api/v1"


def _schedule_two_days(client, bike):
    client.post(f"{API}/schedules", json={"product_id": bike, "production_date": "2026-10-12", "target_qty": 30})
    client.post(f"{API}/schedules", json={"product_id": bike, "production_date": "2026-10-13", "target_qty": 20})
    return client.post(f"{API}/planning/runs",
                       json={"date_from": "2026-10-12", "date_to": "2026-10-13"}).json()


def test_full_flow(client, seeded):
    BIKE, KARET, CIPTA, INDUSTRI = seeded["BIKE"], seeded["KARET"], seeded["CIPTA"], seeded["INDUSTRI"]
    run = _schedule_two_days(client, BIKE)
    by_sku = {l["sku"]: l for l in run["lines"]}
    assert (run["n_critical"], run["n_warning"]) == (2, 2)
    assert by_sku["RM-RUB-01"]["available"] == -20 and by_sku["RM-RUB-01"]["shortfall"] == 60
    assert by_sku["RM-RUB-01"]["status"] == "CRITICAL"
    assert by_sku["RM-STEEL-01"]["status"] == "WARNING" and by_sku["RM-STEEL-01"]["shortfall"] == 25
    assert by_sku["RM-PDL-01"]["shortfall"] == 10

    # Phase 3: sourcing hanya untuk baris defisit
    src = client.get(f"{API}/planning/runs/{run['id']}/sourcing", params={"strategy": "CHEAPEST"}).json()
    assert {s["line"]["sku"] for s in src} == {"RM-RUB-01", "RM-SBR-01", "RM-STEEL-01", "RM-PDL-01"}
    pdl = next(s for s in src if s["line"]["sku"] == "RM-PDL-01")
    assert pdl["deficit"] == 10 and pdl["options"][0]["supplier_name"] == "CV Makmur Bersama"

    # PO belum bisa dibuat sebelum supplier dipilih
    assert client.post(f"{API}/planning/runs/{run['id']}/purchase-orders").status_code == 400

    # Phase 4: pilih supplier + override qty
    pick = {"RM-RUB-01": (KARET, 100), "RM-SBR-01": (CIPTA, 50),
            "RM-STEEL-01": (CIPTA, 100), "RM-PDL-01": (INDUSTRI, 50)}
    for sku, (sup, qty) in pick.items():
        r = client.put(f"{API}/planning/lines/{by_sku[sku]['id']}/selection",
                       json={"supplier_id": sup, "order_qty": qty})
        assert r.status_code == 200

    r = client.post(f"{API}/planning/runs/{run['id']}/purchase-orders")
    assert r.status_code == 201
    pos = r.json()
    totals = {p["supplier_name"]: p["total_amount"] for p in pos}
    assert totals == {"CV Cipta Logam": 3_400_000, "PT Karet Nusantara": 3_500_000,
                      "PT Industri Lokal": 2_400_000}
    cipta = next(p for p in pos if p["supplier_name"] == "CV Cipta Logam")
    assert sorted(i["sku"] for i in cipta["items"]) == ["RM-SBR-01", "RM-STEEL-01"]
    assert client.post(f"{API}/planning/runs/{run['id']}/purchase-orders").status_code == 409
    # pilihan terkunci setelah PO dibuat
    assert client.put(f"{API}/planning/lines/{by_sku['RM-PDL-01']['id']}/selection",
                      json={"supplier_id": INDUSTRI, "order_qty": 60}).status_code == 409

    # Phase 5: terbitkan & terima semua
    for p in pos:
        assert client.patch(f"{API}/purchase-orders/{p['id']}/status",
                            json={"status": "ISSUED"}).status_code == 200
        full = client.get(f"{API}/purchase-orders/{p['id']}").json()
        r = client.post(f"{API}/purchase-orders/{p['id']}/receipts",
                        json={"items": [{"po_item_id": i["id"], "qty_received": i["qty_ordered"]}
                                        for i in full["items"]]})
        assert r.status_code == 200 and r.json()["po_status"] == "RECEIVED"

    inv = {i["sku"]: i for i in client.get(f"{API}/inventory").json()}
    expect = {"RM-RUB-01": (180, 80), "RM-SBR-01": (100, 50), "RM-STEEL-01": (200, 125), "RM-PDL-01": (170, 70)}
    for sku, (oh, av) in expect.items():
        assert inv[sku]["on_hand"] == oh and inv[sku]["available"] == av and inv[sku]["status"] == "SAFE", sku
    assert client.get(f"{API}/inventory", params={"status": "CRITICAL"}).json() == []

    mv = client.get(f"{API}/stock-movements", params={"type": "GOODS_RECEIPT"}).json()
    assert len(mv) == 4 and sum(m["qty"] for m in mv) == 100 + 50 + 100 + 50


def test_replanning_after_po_has_zero_shortfall(client, seeded):
    run = _schedule_two_days(client, seeded["BIKE"])
    client.post(f"{API}/planning/runs/{run['id']}/sourcing/auto-select", json={"strategy": "CHEAPEST"})
    assert client.post(f"{API}/planning/runs/{run['id']}/purchase-orders").status_code == 201
    run2 = client.post(f"{API}/planning/runs",
                       json={"date_from": "2026-10-12", "date_to": "2026-10-13"}).json()
    assert all(l["shortfall"] == 0 for l in run2["lines"])           # berkat on_order
    assert {l["sku"]: l["on_order"] for l in run2["lines"]}["RM-RUB-01"] == 60


def test_auto_select_endpoint(client, seeded):
    run = _schedule_two_days(client, seeded["BIKE"])
    r = client.post(f"{API}/planning/runs/{run['id']}/sourcing/auto-select", json={"strategy": "FASTEST"})
    assert r.status_code == 200 and r.json()["selected"] == 4
    sel = {l["sku"]: l["selected_supplier_name"] for l in r.json()["lines"] if l["shortfall"] > 0}
    assert sel["RM-PDL-01"] == "PT Industri Lokal" and sel["RM-RUB-01"] == "CV Rubber Indonesia"
    assert client.delete(f"{API}/planning/lines/{r.json()['lines'][0]['id']}/selection").status_code == 204
