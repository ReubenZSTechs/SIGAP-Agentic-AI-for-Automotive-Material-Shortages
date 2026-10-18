"""Delta Plan A & B: batch, status jadwal, allocated turunan, dampak stok, stale."""
API = "/api/v1"
MON, TUE, WED = "2026-10-12", "2026-10-13", "2026-10-14"


def sched(client, seeded, day, qty, **extra):
    r = client.post(f"{API}/schedules", json={"product_id": seeded["BIKE"], "production_date": day,
                                              "target_qty": qty, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def inv(client):
    return {i["sku"]: i for i in client.get(f"{API}/inventory").json()}


def status(client, sid, to):
    return client.patch(f"{API}/schedules/{sid}/status", json={"status": to})


def run_plan(client, d1=MON, d2=TUE):
    r = client.post(f"{API}/planning/runs", json={"date_from": d1, "date_to": d2})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_batch_code_line_and_allocated(client, seeded):
    a = sched(client, seeded, MON, 30)
    assert a["batch_code"] == "BATCH-20261012-001" and a["line_code"] == "LINE-01"
    assert a["status"] == "PLANNED" and a["editable"] is True
    assert a["allowed_transitions"] == ["IN_PROGRESS", "CANCELLED"]
    assert (inv(client)["RM-RUB-01"]["allocated"], inv(client)["RM-PDL-01"]["allocated"]) == (60, 60)
    b = sched(client, seeded, TUE, 20, production_line_id=seeded["LINE2"])
    assert b["batch_code"] == "BATCH-20261013-001" and b["line_code"] == "LINE-02"
    c = sched(client, seeded, MON, 5)
    assert c["batch_code"] == "BATCH-20261012-002"                       # NNN per tanggal
    i = inv(client)
    assert (i["RM-RUB-01"]["allocated"], i["RM-PDL-01"]["allocated"]) == (110, 110)
    # B-1: 30 + 20 -> Terkunci Ban 100, Pedal 100, Besi 75, Rangka 50 (tanpa planning)
    client.patch(f"{API}/schedules/{c['id']}/status", json={"status": "CANCELLED"})
    i = inv(client)
    assert [i[s]["allocated"] for s in ("RM-RUB-01", "RM-PDL-01", "RM-STEEL-01", "RM-SBR-01")] == [100, 100, 75, 50]
    assert client.post(f"{API}/schedules", json={"product_id": seeded["BIKE"], "production_date": MON,
                                                 "target_qty": 1, "production_line_id": 9999}).status_code == 404


def test_planning_is_read_only_and_golden_phase2_unchanged(client, seeded):
    sched(client, seeded, MON, 30); sched(client, seeded, TUE, 20)
    before = {k: v["allocated"] for k, v in inv(client).items()}
    run = run_plan(client)
    L = {l["sku"]: l for l in run["lines"]}
    assert (L["RM-RUB-01"]["available"], L["RM-RUB-01"]["shortfall"], L["RM-RUB-01"]["status"]) == (-20, 60, "CRITICAL")
    assert (L["RM-SBR-01"]["available"], L["RM-SBR-01"]["shortfall"]) == (0, 15)
    assert (L["RM-STEEL-01"]["available"], L["RM-STEEL-01"]["shortfall"]) == (25, 25)
    assert (L["RM-PDL-01"]["available"], L["RM-PDL-01"]["shortfall"]) == (20, 10)
    assert {k: v["allocated"] for k, v in inv(client).items()} == before    # run tidak menulis allocated
    # B-8: PUT /inventory tidak mengubah allocated
    mid = seeded["materials"]["RM-RUB-01"]
    r = client.put(f"{API}/inventory/{mid}", json={"on_hand": 90, "safety_stock": 40}).json()
    assert r["allocated"] == 100 and r["on_hand"] == 90
    client.put(f"{API}/inventory/{mid}", json={"on_hand": 80})


def test_allocated_counts_schedules_outside_run_range(client, seeded):
    sched(client, seeded, MON, 30); sched(client, seeded, "2026-10-16", 10)
    run = run_plan(client, MON, MON)                       # rentang hanya Senin
    ban = next(l for l in run["lines"] if l["sku"] == "RM-RUB-01")
    assert ban["gross_requirement"] == 60                  # kebutuhan rentang run
    assert ban["allocated"] == 80 and ban["available"] == 0  # terkunci = SEMUA jadwal PLANNED (konsekuensi desain)


def test_start_production_moves_stock_and_logs_issue(client, seeded):
    mon = sched(client, seeded, MON, 30); sched(client, seeded, TUE, 20)
    r = status(client, mon["id"], "IN_PROGRESS")
    assert r.status_code == 200
    s = r.json()
    assert s["status"] == "IN_PROGRESS" and s["started_at"] and s["editable"] is False
    assert s["allowed_transitions"] == ["COMPLETED"]
    i = inv(client)
    assert (i["RM-RUB-01"]["on_hand"], i["RM-RUB-01"]["allocated"], i["RM-RUB-01"]["available"]) == (20, 40, -20)
    assert (i["RM-PDL-01"]["on_hand"], i["RM-PDL-01"]["allocated"], i["RM-PDL-01"]["available"]) == (60, 40, 20)
    assert (i["RM-STEEL-01"]["on_hand"], i["RM-STEEL-01"]["allocated"], i["RM-STEEL-01"]["available"]) == (55, 30, 25)
    assert (i["RM-SBR-01"]["on_hand"], i["RM-SBR-01"]["allocated"], i["RM-SBR-01"]["available"]) == (20, 20, 0)
    mv = client.get(f"{API}/stock-movements", params={"type": "PRODUCTION_ISSUE"}).json()
    assert len(mv) == 15 and all(m["ref_type"] == "SCHEDULE" and m["ref_id"] == mon["id"] and m["qty"] < 0 for m in mv)
    assert next(m for m in mv if m["sku"] == "RM-RUB-01")["qty"] == -60
    assert mv[0]["note"] == "BATCH-20261012-001"


def test_start_rejected_when_stock_short_is_atomic_then_cancel_releases_allocation(client, seeded):
    mon = sched(client, seeded, MON, 30); tue = sched(client, seeded, TUE, 20)
    assert status(client, mon["id"], "IN_PROGRESS").status_code == 200
    moves_before = len(client.get(f"{API}/stock-movements").json())
    before = inv(client)
    r = status(client, tue["id"], "IN_PROGRESS")
    assert r.status_code == 409
    body = r.json()
    assert body["detail"].startswith("Stok fisik tidak cukup")
    assert [(x["sku"], x["required"], x["on_hand"], x["short_by"]) for x in body["shortages"]] == [("RM-RUB-01", 40, 20, 20)]
    assert inv(client) == before                                                   # tidak ada perubahan stok
    assert len(client.get(f"{API}/stock-movements").json()) == moves_before        # tidak ada movement
    assert client.get(f"{API}/schedules", params={"status": "PLANNED"}).json()[0]["id"] == tue["id"]
    # batalkan PLANNED -> Terkunci turun, on_hand tetap
    assert status(client, tue["id"], "CANCELLED").status_code == 200
    i = inv(client)
    assert all(i[s]["allocated"] == 0 for s in ("RM-RUB-01", "RM-PDL-01", "RM-STEEL-01", "RM-SBR-01"))
    assert (i["RM-RUB-01"]["on_hand"], i["RM-RUB-01"]["status"]) == (20, "WARNING")
    assert (i["RM-PDL-01"]["status"], i["RM-STEEL-01"]["status"], i["RM-SBR-01"]["status"]) == ("SAFE", "SAFE", "SAFE")
    # selesai: tanpa efek stok
    assert status(client, mon["id"], "COMPLETED").json()["completed_at"]
    assert inv(client) == i and len(client.get(f"{API}/stock-movements").json()) == moves_before


def test_status_transitions_and_edit_locks(client, seeded):
    a = sched(client, seeded, MON, 5)
    assert status(client, a["id"], "COMPLETED").status_code == 409                 # PLANNED -> COMPLETED
    assert client.patch(f"{API}/schedules/{a['id']}/status", json={"status": "PLANNED"}).status_code == 422
    assert client.patch(f"{API}/schedules/{a['id']}", json={"status": "COMPLETED"}).status_code == 422  # status tak lagi di PATCH
    status(client, a["id"], "IN_PROGRESS")
    assert client.patch(f"{API}/schedules/{a['id']}", json={"target_qty": 9}).status_code == 409
    assert client.delete(f"{API}/schedules/{a['id']}").status_code == 409
    assert status(client, a["id"], "CANCELLED").status_code == 409
    status(client, a["id"], "COMPLETED")
    for to in ("IN_PROGRESS", "COMPLETED", "CANCELLED"):
        assert status(client, a["id"], to).status_code == 409
    b = sched(client, seeded, TUE, 5)
    assert client.delete(f"{API}/schedules/{b['id']}").status_code == 204          # alias pembatalan
    assert status(client, b["id"], "IN_PROGRESS").status_code == 409               # CANCELLED terminal
    assert status(client, 9999, "CANCELLED").status_code == 404


def test_edit_planned_recalcs_and_validates(client, seeded):
    a = sched(client, seeded, MON, 30)
    r = client.patch(f"{API}/schedules/{a['id']}", json={"target_qty": 10, "production_date": WED})
    assert r.status_code == 200 and r.json()["batch_code"] == a["batch_code"]      # kode immutable
    assert inv(client)["RM-RUB-01"]["allocated"] == 20
    prod2 = client.post(f"{API}/products", json={"sku": "FG-NOBOM", "name": "x", "selling_price": 1}).json()
    assert client.patch(f"{API}/schedules/{a['id']}", json={"product_id": prod2["id"]}).status_code == 422
    assert client.patch(f"{API}/schedules/{a['id']}", json={"product_id": seeded["materials"]["RM-PDL-01"]}).status_code == 422
    assert inv(client)["RM-RUB-01"]["allocated"] == 20                             # gagal -> tidak berubah


def test_bom_incomplete_or_cycle_is_422_for_schedules(client, seeded):
    prod = client.post(f"{API}/products", json={"sku": "FG-X", "name": "x", "selling_price": 1}).json()
    sub = client.post(f"{API}/bom/sub-parts", json={"parent_id": prod["id"], "sku": "SA-X", "name": "s",
                                                    "uom": "Set", "qty_per_parent": 1}).json()
    body = {"product_id": prod["id"], "production_date": MON, "target_qty": 1}
    assert client.post(f"{API}/schedules", json=body).status_code == 422          # sub-part tanpa komponen
    pdl = seeded["materials"]["RM-PDL-01"]
    client.post(f"{API}/bom/items", json={"parent_id": sub["child_id"], "child_id": pdl, "qty_per_parent": 1})
    assert client.post(f"{API}/schedules", json=body).status_code == 201


def test_bom_edit_recalcs_allocated_and_is_tolerant(client, seeded):
    sched(client, seeded, MON, 30)
    tree = client.get(f"{API}/bom/{seeded['BIKE']}/tree").json()
    wheel = next(c for c in tree["children"] if c["material"]["sku"] == "SA-WHEEL-01")
    ban = next(c for c in wheel["children"] if c["material"]["sku"] == "RM-RUB-01")
    assert inv(client)["RM-RUB-01"]["allocated"] == 60
    client.patch(f"{API}/bom/items/{ban['bom_item_id']}", json={"qty_per_parent": 4})
    assert inv(client)["RM-RUB-01"]["allocated"] == 120                            # B-7
    # sub-part kosong sementara TIDAK boleh memblokir edit BOM
    r = client.post(f"{API}/bom/sub-parts", json={"parent_id": seeded["BIKE"], "sku": "SA-TMP", "name": "t",
                                                  "uom": "Set", "qty_per_parent": 1})
    assert r.status_code == 201
    assert inv(client)["RM-RUB-01"]["allocated"] == 0                              # tolerant: produk tak lengkap dihitung 0
    assert client.post(f"{API}/planning/runs", json={"date_from": MON, "date_to": MON}).status_code == 422  # planning tetap strict
    client.delete(f"{API}/bom/items/{r.json()['id']}")
    assert inv(client)["RM-RUB-01"]["allocated"] == 120                            # pulih setelah BOM lengkap lagi


def test_stale_runs_on_schedule_change_blocks_po_and_rerun_clears(client, seeded):
    sched(client, seeded, MON, 30); tue = sched(client, seeded, TUE, 20)
    run = run_plan(client)
    assert run["is_stale"] is False
    client.post(f"{API}/planning/runs/{run['id']}/sourcing/auto-select", json={})
    # drag Selasa -> Rabu
    assert client.patch(f"{API}/schedules/{tue['id']}", json={"production_date": WED}).status_code == 200
    assert client.get(f"{API}/planning/runs/{run['id']}").json()["is_stale"] is True
    r = client.post(f"{API}/planning/runs/{run['id']}/purchase-orders")
    assert r.status_code == 409 and "basi" in r.json()["detail"].lower()
    run2 = run_plan(client, MON, WED)
    assert run2["is_stale"] is False
    assert {l["sku"]: l["available"] for l in run2["lines"]}["RM-RUB-01"] == -20  # angka Phase 2 sama
    assert client.get(f"{API}/planning/runs/{run['id']}").json()["is_stale"] is True   # run lama tetap basi
    # jadwal di luar rentang run tetap membuat run DRAFT basi (allocated global)
    sched(client, seeded, "2026-10-16", 10)
    assert client.get(f"{API}/planning/runs/{run2['id']}").json()["is_stale"] is True


def test_start_and_receipt_do_not_mark_runs_stale(client, seeded):
    mon = sched(client, seeded, MON, 30); sched(client, seeded, TUE, 20)
    run = run_plan(client)
    status(client, mon["id"], "IN_PROGRESS")                                        # available & on_order tetap
    assert client.get(f"{API}/planning/runs/{run['id']}").json()["is_stale"] is False
    # penyesuaian stok manual memengaruhi shortfall -> basi
    mid = seeded["materials"]["RM-PDL-01"]
    client.put(f"{API}/inventory/{mid}", json={"safety_stock": 35})
    assert client.get(f"{API}/planning/runs/{run['id']}").json()["is_stale"] is True


def test_schedule_materials_endpoint(client, seeded):
    mon = sched(client, seeded, MON, 30); sched(client, seeded, TUE, 20)
    d = client.get(f"{API}/schedules/{mon['id']}/materials").json()
    assert d["basis"] == "CURRENT_BOM" and d["scope"] == "GLOBAL_STOCK_STATUS" and d["can_start"] is True
    assert len(d["lines"]) == 15
    ban = next(l for l in d["lines"] if l["sku"] == "RM-RUB-01")
    assert (ban["required_qty"], ban["on_hand"], ban["allocated"], ban["available"], ban["on_hand_after"]) == (60, 80, 100, -20, 20)
    assert ban["enough"] is True and ban["status"] == "CRITICAL"                    # status GLOBAL material
    client.put(f"{API}/inventory/{seeded['materials']['RM-RUB-01']}", json={"on_hand": 50})
    d = client.get(f"{API}/schedules/{mon['id']}/materials").json()
    assert d["can_start"] is False and next(l for l in d["lines"] if l["sku"] == "RM-RUB-01")["enough"] is False
    client.put(f"{API}/inventory/{seeded['materials']['RM-RUB-01']}", json={"on_hand": 80})
    status(client, mon["id"], "IN_PROGRESS")
    d = client.get(f"{API}/schedules/{mon['id']}/materials").json()
    assert d["can_start"] is False and all(l["on_hand_after"] is None for l in d["lines"])
    assert client.get(f"{API}/schedules/9999/materials").status_code == 404


def test_lists_lines_and_filters(client, seeded):
    lines = client.get(f"{API}/production-lines").json()
    assert [l["code"] for l in lines] == ["LINE-01", "LINE-02"]
    sched(client, seeded, MON, 5); b = sched(client, seeded, TUE, 5, production_line_id=seeded["LINE2"])
    out = client.get(f"{API}/schedules", params={"production_line_id": seeded["LINE2"]}).json()
    assert [s["id"] for s in out] == [b["id"]]
    assert {"batch_code", "product_sku", "product_name", "line_code", "started_at", "editable",
            "allowed_transitions"} <= out[0].keys()
    assert len(client.get(f"{API}/schedules", params={"date_from": TUE}).json()) == 1


def test_recalc_is_from_scratch_and_idempotent(db, client, seeded):
    from app.models import Inventory
    from app.services import allocation_service
    sched(client, seeded, MON, 30)
    db.expire_all()
    inv_rows = db.query(Inventory).all()
    for i in inv_rows:
        i.allocated = 999.0                                                         # korupsi sengaja
    db.commit()
    assert allocation_service.recalc_allocated(db) is True
    db.commit()
    snap = {i.material_id: i.allocated for i in db.query(Inventory).all()}
    assert allocation_service.recalc_allocated(db) is False                        # idempoten
    assert snap[seeded["materials"]["RM-RUB-01"]] == 60
    assert snap[seeded["materials"]["RM-SCR-01"]] == 600 and snap[seeded["materials"]["RM-VNL-01"]] == 6
