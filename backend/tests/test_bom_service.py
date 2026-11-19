import pytest

from app.core.exceptions import AppError
from app.models import BOMItem, Material
from app.models.enums import ItemCategory, ProcurementType
from app.services import bom_service


def _mat(db, sku, t):
    cat = ItemCategory.SUB_PART if t == ProcurementType.MAKE else ItemCategory.PURCHASED
    m = Material(sku=sku, name=sku, uom="pcs", category=cat)
    db.add(m)
    db.flush()
    return m


def test_explode_seed_one_unit(db, seeded):
    res = bom_service.explode(db, seeded["BIKE"], 1)
    m = seeded["materials"]
    assert res[m["RM-RUB-01"]] == 2          # Roda Set 1 x Ban Luar 2
    assert res[m["RM-STEEL-01"]] == 1.5
    assert res[m["RM-PDL-01"]] == 2
    assert res[m["RM-SBR-01"]] == 1
    assert len(res) == 15                     # seluruh material BUY


def test_explode_three_level_nested(db):
    a = _mat(db, "A", ProcurementType.MAKE)
    b = _mat(db, "B", ProcurementType.MAKE)
    c = _mat(db, "C", ProcurementType.MAKE)
    leaf = _mat(db, "LEAF", ProcurementType.BUY)
    db.add_all([BOMItem(parent_id=a.id, child_id=b.id, qty_per_parent=2),
                BOMItem(parent_id=b.id, child_id=c.id, qty_per_parent=3),
                BOMItem(parent_id=c.id, child_id=leaf.id, qty_per_parent=1.5)])
    db.commit()
    assert bom_service.explode(db, a.id, 10) == {leaf.id: 10 * 2 * 3 * 1.5}


def test_make_without_bom_is_422(db):
    a = _mat(db, "A", ProcurementType.MAKE)
    b = _mat(db, "B", ProcurementType.MAKE)
    db.add(BOMItem(parent_id=a.id, child_id=b.id, qty_per_parent=1))
    db.commit()
    with pytest.raises(AppError) as e:
        bom_service.explode(db, a.id)
    assert e.value.status_code == 422


def test_explode_non_make_product_is_422(db, seeded):
    with pytest.raises(AppError) as e:
        bom_service.explode(db, seeded["materials"]["RM-PDL-01"])
    assert e.value.status_code == 422


def test_cycle_detection_service_and_api(db, client):
    a = _mat(db, "A", ProcurementType.MAKE)
    b = _mat(db, "B", ProcurementType.MAKE)
    db.add(BOMItem(parent_id=a.id, child_id=b.id, qty_per_parent=1))
    db.commit()
    assert bom_service.would_create_cycle(db, b.id, a.id) is True
    assert bom_service.would_create_cycle(db, a.id, b.id) is False
    r = client.post("/api/v1/bom/items", json={"parent_id": b.id, "child_id": a.id, "qty_per_parent": 1})
    assert r.status_code == 409
    r = client.post("/api/v1/bom/items", json={"parent_id": a.id, "child_id": a.id, "qty_per_parent": 1})
    assert r.status_code == 409           # self-reference = siklus


def test_explosion_guard_detects_cycle_in_data(db):
    a = _mat(db, "A", ProcurementType.MAKE)
    b = _mat(db, "B", ProcurementType.MAKE)
    db.add_all([BOMItem(parent_id=a.id, child_id=b.id, qty_per_parent=1),
                BOMItem(parent_id=b.id, child_id=a.id, qty_per_parent=1)])   # bypass cek insert
    db.commit()
    with pytest.raises(AppError) as e:
        bom_service.explode(db, a.id)
    assert e.value.status_code == 409


def test_bom_api_tree_explosion_and_replace(client, seeded):
    bike = seeded["BIKE"]
    tree = client.get(f"/api/v1/bom/{bike}/tree").json()
    assert tree["level"] == 0 and len(tree["children"]) == 4
    wheel = next(c for c in tree["children"] if c["material"]["sku"] == "SA-WHEEL-01")
    rub = next(c for c in wheel["children"] if c["material"]["sku"] == "RM-RUB-01")
    assert rub["level"] == 2 and rub["qty_cumulative"] == 2

    ex = client.get(f"/api/v1/bom/{bike}/explosion", params={"qty": 50}).json()
    by_sku = {r["sku"]: r["gross_qty"] for r in ex}
    assert by_sku["RM-RUB-01"] == 100 and by_sku["RM-STEEL-01"] == 75 and by_sku["RM-PDL-01"] == 100
    assert by_sku["RM-VNL-01"] == 10

    # replace-all: SA-DRIVE-01 hanya berisi pedal x4
    drive = seeded["materials"]["SA-DRIVE-01"]
    pedal = seeded["materials"]["RM-PDL-01"]
    r = client.put(f"/api/v1/bom/{drive}/items", json=[{"child_id": pedal, "qty_per_parent": 4}])
    assert r.status_code == 200 and len(r.json()) == 1 and r.json()[0]["qty_per_parent"] == 4
    ex = client.get(f"/api/v1/bom/{bike}/explosion").json()
    assert {r["sku"]: r["gross_qty"] for r in ex}["RM-PDL-01"] == 4

    # replace-all dengan siklus ditolak & BOM lama tetap utuh (rollback)
    r = client.put(f"/api/v1/bom/{drive}/items", json=[{"child_id": drive, "qty_per_parent": 1}])  # siklus (diri sendiri)
    assert r.status_code == 409
    assert len(client.get(f"/api/v1/bom/{bike}/explosion").json()) == 15 - 2   # hdl & chn sudah terhapus
    assert client.post("/api/v1/bom/items", json={"parent_id": pedal, "child_id": bike,
                                                  "qty_per_parent": 1}).status_code == 422  # parent BUY
