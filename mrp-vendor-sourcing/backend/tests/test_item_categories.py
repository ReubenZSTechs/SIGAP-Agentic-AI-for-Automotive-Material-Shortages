"""Pemisahan Produk Final / Material Beli / Sub-part (kategori "Made")."""
API = "/api/v1"


def test_seed_categories_and_derived_procurement_type(client, seeded):
    mats = {m["sku"]: m for m in client.get(f"{API}/materials", params={"limit": 500}).json()}
    assert mats["FG-BIKE-01"]["category"] == "FINISHED" and mats["FG-BIKE-01"]["procurement_type"] == "MAKE"
    assert mats["SA-WHEEL-01"]["category"] == "SUB_PART" and mats["SA-WHEEL-01"]["procurement_type"] == "MAKE"
    assert mats["RM-PDL-01"]["category"] == "PURCHASED" and mats["RM-PDL-01"]["procurement_type"] == "BUY"


def test_materials_endpoint_is_purchased_only(client, seeded):
    # input lama (procurement_type / category) ditolak
    r = client.post(f"{API}/materials", json={"sku": "X-1", "name": "x", "uom": "kg", "procurement_type": "MAKE"})
    assert r.status_code == 422
    r = client.post(f"{API}/materials", json={"sku": "X-1", "name": "x", "uom": "kg", "category": "SUB_PART"})
    assert r.status_code == 422
    # sub-part & produk final tidak bisa diubah/dihapus lewat /materials
    sub = seeded["materials"]["SA-FRAME-01"]
    assert client.patch(f"{API}/materials/{sub}", json={"name": "x"}).status_code == 422
    assert client.delete(f"{API}/materials/{seeded['BIKE']}").status_code == 422


def test_products_crud(client, seeded):
    lst = client.get(f"{API}/products").json()
    assert [p["sku"] for p in lst] == ["FG-BIKE-01"]
    assert lst[0]["selling_price"] == 4_500_000 and lst[0]["bom_item_count"] == 4
    r = client.post(f"{API}/products", json={"sku": "FG-BIKE-02", "name": "Sepeda Lipat", "selling_price": 3_000_000,
                                             "specification": "20 inci"})
    assert r.status_code == 201
    p = r.json()
    assert p["uom"] == "Unit" and p["bom_item_count"] == 0 and p["specification"] == "20 inci"
    assert client.post(f"{API}/products", json={"sku": "FG-BIKE-02", "name": "dup", "selling_price": 1}).status_code == 409
    assert client.post(f"{API}/products", json={"sku": "FG-X", "name": "x", "selling_price": -1}).status_code == 422
    assert client.patch(f"{API}/products/{p['id']}", json={"selling_price": 3_200_000}).json()["selling_price"] == 3_200_000
    assert client.patch(f"{API}/products/{p['id']}", json={"name": None}).status_code == 422
    # material beli / sub-part bukan produk
    assert client.get(f"{API}/products/{seeded['materials']['RM-PDL-01']}").status_code == 404
    assert client.get(f"{API}/products", params={"q": "lipat"}).json()[0]["sku"] == "FG-BIKE-02"
    # produk tanpa BOM tidak bisa dijadwalkan (422); setelah BOM terisi bisa; yang dipakai tidak bisa dihapus
    sched = {"product_id": p["id"], "production_date": "2026-10-12", "target_qty": 3}
    assert client.post(f"{API}/schedules", json=sched).status_code == 422
    assert client.post(f"{API}/bom/items", json={"parent_id": p["id"], "child_id": seeded["materials"]["RM-PDL-01"],
                                                 "qty_per_parent": 1}).status_code == 201
    assert client.post(f"{API}/schedules", json=sched).status_code == 201
    assert client.delete(f"{API}/products/{p['id']}").status_code == 409
    assert client.delete(f"{API}/products/{seeded['BIKE']}").status_code == 409
    p2 = client.post(f"{API}/products", json={"sku": "FG-TMP", "name": "tmp", "selling_price": 1}).json()
    assert client.delete(f"{API}/products/{p2['id']}").status_code == 204


def test_define_new_product_structure_via_bom(client, seeded):
    """Produk baru -> sub-part baru lewat BOM -> material beli -> eksplosi -> planning."""
    prod = client.post(f"{API}/products", json={"sku": "FG-NEW", "name": "Sepeda Baru", "selling_price": 1_000_000}).json()
    pdl = seeded["materials"]["RM-PDL-01"]
    # 1) sub-part baru dibuat langsung dari BOM (atomik)
    r = client.post(f"{API}/bom/sub-parts", json={"parent_id": prod["id"], "sku": "SA-NEW-01",
                                                  "name": "Rakitan Baru", "uom": "Set", "qty_per_parent": 2})
    assert r.status_code == 201
    item = r.json()
    assert item["child_category"] == "SUB_PART" and item["qty_per_parent"] == 2
    sub_id = item["child_id"]
    # 2) material beli ditambahkan di bawah sub-part
    assert client.post(f"{API}/bom/items", json={"parent_id": sub_id, "child_id": pdl, "qty_per_parent": 3}).status_code == 201
    # 3) eksplosi: 2 x 3 = 6 pedal per produk
    ex = {r["sku"]: r["gross_qty"] for r in client.get(f"{API}/bom/{prod['id']}/explosion").json()}
    assert ex == {"RM-PDL-01": 6}
    assert client.get(f"{API}/products").json()[-1]["bom_item_count"] == 1
    # 4) sub-part dapat dipakai ulang di produk lain; rename lewat BOM
    assert client.post(f"{API}/bom/items", json={"parent_id": seeded["BIKE"], "child_id": sub_id,
                                                 "qty_per_parent": 1}).status_code == 201
    r = client.patch(f"{API}/bom/sub-parts/{sub_id}", json={"name": "Rakitan Baru v2"})
    assert r.status_code == 200 and r.json()["name"] == "Rakitan Baru v2"
    assert client.patch(f"{API}/bom/sub-parts/{pdl}", json={"name": "x"}).status_code == 422   # bukan sub-part
    # 5) produk final terjadwal -> planning memakai struktur baru
    client.post(f"{API}/schedules", json={"product_id": prod["id"], "production_date": "2026-10-12", "target_qty": 10})
    run = client.post(f"{API}/planning/runs", json={"date_from": "2026-10-12", "date_to": "2026-10-12"}).json()
    assert {l["sku"]: l["gross_requirement"] for l in run["lines"]}["RM-PDL-01"] == 60


def test_bom_rules_for_new_categories(client, seeded):
    pdl, bike = seeded["materials"]["RM-PDL-01"], seeded["BIKE"]
    frame = seeded["materials"]["SA-FRAME-01"]
    # sku bentrok
    r = client.post(f"{API}/bom/sub-parts", json={"parent_id": bike, "sku": "RM-PDL-01", "name": "x",
                                                  "uom": "Set", "qty_per_parent": 1})
    assert r.status_code == 409
    # parent material beli ditolak
    r = client.post(f"{API}/bom/sub-parts", json={"parent_id": pdl, "sku": "SA-Z", "name": "x",
                                                  "uom": "Set", "qty_per_parent": 1})
    assert r.status_code == 422
    # produk final tidak boleh jadi komponen
    prod2 = client.post(f"{API}/products", json={"sku": "FG-2", "name": "P2", "selling_price": 1}).json()
    r = client.post(f"{API}/bom/items", json={"parent_id": frame, "child_id": prod2["id"], "qty_per_parent": 1})
    assert r.status_code == 422
    r = client.put(f"{API}/bom/{frame}/items", json=[{"child_id": prod2["id"], "qty_per_parent": 1}])
    assert r.status_code == 422
    # tree membawa kategori
    tree = client.get(f"{API}/bom/{bike}/tree").json()
    assert tree["material"]["category"] == "FINISHED"
    assert {c["material"]["category"] for c in tree["children"]} == {"SUB_PART"}
