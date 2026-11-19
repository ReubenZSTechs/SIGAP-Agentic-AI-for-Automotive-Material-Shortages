"""Delta Plan C: Manual PO, approval, mesin transisi per source, on_order."""
from tests.test_schedule_stock_sync import API, MON, TUE, inv, run_plan, sched

NEXT_WEEK = "2026-10-20"


def manual(client, seeded, **over):
    body = {"supplier_id": seeded["KARET"], "po_date": "2026-10-13", "notes": "mendesak",
            "items": [{"material_id": seeded["materials"]["RM-RUB-01"], "qty_ordered": 100,
                       "unit_price": 35000, "needed_by_date": "2026-10-18"}], **over}
    return client.post(f"{API}/purchase-orders", json=body)


def act(client, po_id, what, **body):
    if what in ("submit", "approve", "reject"):
        return client.post(f"{API}/purchase-orders/{po_id}/{what}", json=body or None)
    return client.patch(f"{API}/purchase-orders/{po_id}/status", json={"status": what})


def test_create_manual_po_fields_and_not_counted_as_on_order_while_draft(client, seeded):
    r = manual(client, seeded)
    assert r.status_code == 201, r.text
    po = r.json()
    assert po["status"] == "DRAFT" and po["source"] == "MANUAL" and po["planning_run_id"] is None
    assert po["total_amount"] == 3_500_000 and po["po_date"] == "2026-10-13" and po["notes"] == "mendesak"
    assert po["payment_term_days"] == 30 and po["warnings"] == []
    item = po["items"][0]
    assert item["sku"] == "RM-RUB-01" and item["uom"] == "Buah" and item["needed_by_date"] == "2026-10-18"
    assert inv(client)["RM-RUB-01"]["on_order"] == 0                                # DRAFT manual tidak dihitung
    assert client.get(f"{API}/purchase-orders", params={"source": "MANUAL"}).json()[0]["id"] == po["id"]
    assert client.get(f"{API}/purchase-orders", params={"source": "PLANNING"}).json() == []


def test_manual_po_validations(client, seeded):
    rub, pdl = seeded["materials"]["RM-RUB-01"], seeded["materials"]["RM-PDL-01"]
    item = {"material_id": rub, "qty_ordered": 10, "unit_price": 100}
    bad = [
        ({"items": []}, 422), ({"items": [item, item]}, 422),
        ({"items": [{**item, "qty_ordered": 0}]}, 422), ({"items": [{**item, "unit_price": -1}]}, 422),
        ({"items": [{**item, "needed_by_date": "2026-10-01"}]}, 422),               # < po_date
        ({"items": [{**item, "material_id": seeded["materials"]["SA-FRAME-01"]}]}, 422),  # sub-part bukan material beli
        ({"items": [{**item, "material_id": seeded["BIKE"]}]}, 422),
        ({"items": [{**item, "material_id": 99999}]}, 404), ({"supplier_id": 99999}, 404),
    ]
    for over, code in bad:
        r = manual(client, seeded, **over)
        assert r.status_code == code, (over, r.status_code, r.text)
    # supplier nonaktif
    client.patch(f"{API}/suppliers/{seeded['MAKMUR']}", json={"is_active": False})
    assert manual(client, seeded, supplier_id=seeded["MAKMUR"]).status_code == 422
    # supplier tidak terhubung ke material -> peringatan, BUKAN blokir
    r = manual(client, seeded, supplier_id=seeded["INDUSTRI"])                       # Industri tidak jual Ban
    assert r.status_code == 201 and r.json()["warnings"] == ["RM-RUB-01: supplier belum terdaftar untuk material ini"]
    ok = manual(client, seeded, items=[item, {"material_id": pdl, "qty_ordered": 1, "unit_price": 0}])
    assert ok.status_code == 201 and ok.json()["total_amount"] == 1000              # harga 0 diperbolehkan


def test_full_approval_flow_on_order_and_goods_receipt(client, seeded):
    sched(client, seeded, MON, 30); sched(client, seeded, TUE, 20)
    po = manual(client, seeded).json()
    ban = lambda: next(l for l in run_plan(client)["lines"] if l["sku"] == "RM-RUB-01")
    assert ban()["on_order"] == 0 and ban()["shortfall"] == 60                      # DRAFT belum dihitung
    run = run_plan(client)
    r = act(client, po["id"], "submit")
    assert r.status_code == 200 and r.json()["status"] == "PENDING_APPROVAL" and r.json()["submitted_at"]
    assert client.get(f"{API}/planning/runs/{run['id']}").json()["is_stale"] is True   # set on_order berubah -> basi
    assert inv(client)["RM-RUB-01"]["on_order"] == 100
    b = ban()
    assert (b["on_order"], b["available"], b["shortfall"]) == (100, -20, 0)          # cegah pesan ganda
    r = act(client, po["id"], "approve", approved_by="Budi")
    assert r.json()["status"] == "APPROVED" and r.json()["decided_by"] == "Budi" and r.json()["decided_at"]
    assert inv(client)["RM-RUB-01"]["on_order"] == 100
    assert act(client, po["id"], "ISSUED").json()["status"] == "ISSUED"
    item = client.get(f"{API}/purchase-orders/{po['id']}").json()["items"][0]
    run = run_plan(client)
    r = client.post(f"{API}/purchase-orders/{po['id']}/receipts", json={"items": [{"po_item_id": item["id"], "qty_received": 100}]})
    assert r.status_code == 200 and r.json()["po_status"] == "RECEIVED"
    i = inv(client)["RM-RUB-01"]
    assert (i["on_hand"], i["on_order"], i["allocated"], i["available"], i["status"]) == (180, 0, 100, 80, "SAFE")  # Phase 5
    assert client.get(f"{API}/planning/runs/{run['id']}").json()["is_stale"] is False  # penerimaan netral
    mv = client.get(f"{API}/stock-movements", params={"type": "GOODS_RECEIPT"}).json()
    assert mv[0]["ref_type"] == "PO" and mv[0]["qty"] == 100


def test_reject_edit_resubmit_approve(client, seeded):
    po = manual(client, seeded).json()
    act(client, po["id"], "submit")
    assert act(client, po["id"], "reject", rejected_by="Sari", reason="x").status_code == 422      # alasan min 3
    r = act(client, po["id"], "reject", rejected_by="Sari", reason="harga di atas kontrak")
    assert r.json()["status"] == "REJECTED" and r.json()["rejection_reason"] == "harga di atas kontrak"
    assert r.json()["decided_by"] == "Sari" and inv(client)["RM-RUB-01"]["on_order"] == 0
    it = {"material_id": seeded["materials"]["RM-RUB-01"], "qty_ordered": 120, "unit_price": 34000}
    r = client.patch(f"{API}/purchase-orders/{po['id']}", json={"items": [it], "notes": "revisi"})
    assert r.status_code == 200 and r.json()["total_amount"] == 4_080_000 and r.json()["status"] == "REJECTED"
    r = act(client, po["id"], "submit")
    assert r.json()["status"] == "PENDING_APPROVAL" and r.json()["rejection_reason"] is None and r.json()["decided_by"] is None
    assert act(client, po["id"], "approve", approved_by="Budi").json()["status"] == "APPROVED"


def test_invalid_transitions_and_edit_rules(client, seeded):
    po = manual(client, seeded).json()
    pid = po["id"]
    item = po["items"][0]
    assert act(client, pid, "approve", approved_by="Budi").status_code == 409            # DRAFT
    assert act(client, pid, "reject", rejected_by="Budi", reason="alasan").status_code == 409
    assert act(client, pid, "ISSUED").status_code == 409                                  # manual wajib approval
    rcpt = {"items": [{"po_item_id": item["id"], "qty_received": 1}]}
    assert client.post(f"{API}/purchase-orders/{pid}/receipts", json=rcpt).status_code == 409   # DRAFT
    act(client, pid, "submit")
    assert client.patch(f"{API}/purchase-orders/{pid}", json={"notes": "x"}).status_code == 409  # PENDING tidak boleh diedit
    assert act(client, pid, "submit").status_code == 409
    act(client, pid, "approve", approved_by="Budi")
    assert client.post(f"{API}/purchase-orders/{pid}/receipts", json=rcpt).status_code == 409   # APPROVED
    assert act(client, pid, "approve", approved_by="Budi").status_code == 409
    act(client, pid, "ISSUED")
    assert client.patch(f"{API}/purchase-orders/{pid}", json={"notes": "x"}).status_code == 409
    assert act(client, pid, "RECEIVED").status_code == 422                                 # bukan nilai yang diizinkan
    assert act(client, pid, "CANCELLED").json()["status"] == "CANCELLED"
    assert act(client, pid, "ISSUED").status_code == 409
    assert act(client, 99999, "submit").status_code == 404


def test_cancel_counted_manual_po_marks_runs_stale_and_drops_on_order(client, seeded):
    sched(client, seeded, MON, 30)
    po = manual(client, seeded).json()
    act(client, po["id"], "submit")
    run = run_plan(client)
    assert next(l for l in run["lines"] if l["sku"] == "RM-RUB-01")["on_order"] == 100
    assert act(client, po["id"], "CANCELLED").json()["status"] == "CANCELLED"
    assert inv(client)["RM-RUB-01"]["on_order"] == 0
    assert client.get(f"{API}/planning/runs/{run['id']}").json()["is_stale"] is True


def test_planning_po_flow_unchanged_and_not_editable_or_approvable(client, seeded):
    sched(client, seeded, MON, 30); sched(client, seeded, TUE, 20)
    run = run_plan(client)
    client.post(f"{API}/planning/runs/{run['id']}/sourcing/auto-select", json={"strategy": "CHEAPEST"})
    pos = client.post(f"{API}/planning/runs/{run['id']}/purchase-orders").json()
    assert pos and all(p["source"] == "PLANNING" and p["status"] == "DRAFT" for p in pos)
    p = pos[0]
    assert p["po_date"] and p["payment_term_days"] >= 0
    assert inv(client)["RM-RUB-01"]["on_order"] == 60                                     # DRAFT planning DIHITUNG (alur lama)
    assert act(client, p["id"], "submit").status_code == 409
    assert act(client, p["id"], "approve", approved_by="Budi").status_code == 409
    assert client.patch(f"{API}/purchase-orders/{p['id']}", json={"notes": "x"}).status_code == 409
    assert act(client, p["id"], "ISSUED").json()["status"] == "ISSUED"                    # DRAFT -> ISSUED tanpa approval


def test_supplier_payment_term_crud(client, seeded):
    r = client.post(f"{API}/suppliers", json={"code": "SUP-T", "name": "T", "payment_term_days": 45})
    assert r.status_code == 201 and r.json()["payment_term_days"] == 45
    assert client.patch(f"{API}/suppliers/{r.json()['id']}", json={"payment_term_days": 60}).json()["payment_term_days"] == 60
    assert client.post(f"{API}/suppliers", json={"code": "SUP-U", "name": "U", "payment_term_days": -1}).status_code == 422
    assert client.post(f"{API}/suppliers", json={"code": "SUP-V", "name": "V"}).json()["payment_term_days"] == 0


def test_update_manual_supplier_change_revalidates_and_warns(client, seeded):
    po = manual(client, seeded).json()
    r = client.patch(f"{API}/purchase-orders/{po['id']}", json={"supplier_id": seeded["INDUSTRI"]})
    assert r.status_code == 200 and r.json()["supplier_name"] == "PT Industri Lokal" and r.json()["warnings"]
    assert client.patch(f"{API}/purchase-orders/{po['id']}", json={"po_date": "2026-10-25"}).status_code == 422  # needed_by < po_date
    dup = {"material_id": seeded["materials"]["RM-RUB-01"], "qty_ordered": 1, "unit_price": 1}
    assert client.patch(f"{API}/purchase-orders/{po['id']}", json={"items": [dup, dup]}).status_code == 422
