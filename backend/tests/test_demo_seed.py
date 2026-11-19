"""The demo seed (`scripts/seed.py`, automotive catalogue) loads and is usable by the app.

The other tests run on the fixed bicycle scenario in `tests/spec_seed.py`; this file checks the real
demo data: integrity rules, BOM depth down to purchased parts, sourcing coverage, the SokratesCar
supplier rule, and that planning works on its demo schedules.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import MaterialSupplier, Schedule, Supplier
from app.services import bom_service, planning_service
from scripts import seed as demo


@pytest.fixture()
def demo_ids(db):
    return demo.seed(db, with_schedules=True)


def test_seed_tables_pass_their_own_validation():
    demo.validate_seed_data()                       # raises ValueError listing every problem
    assert len({s for s, *_ in demo.SUPPLIERS}) == len(demo.SUPPLIERS) == 36
    assert len(demo.FINISHED) == 21


def test_validation_reports_broken_data(monkeypatch):
    sku = next(s for s, _n, _u, c in demo.MATERIALS if c == demo.BUY and not s.startswith("RM-SKR-"))
    monkeypatch.setitem(demo.SOURCING, sku, [])
    monkeypatch.setattr(demo, "BOM", [*demo.BOM, ("FG-HB-ICE-01", "FG-SDN-ICE-02", 1)])
    with pytest.raises(ValueError) as e:
        demo.validate_seed_data()
    assert "FINISHED item cannot be a BOM child: FG-SDN-ICE-02" in str(e.value)


def test_every_vehicle_explodes_to_purchased_parts_with_a_supplier(db, demo_ids):
    linked = set(db.scalars(select(MaterialSupplier.material_id).where(MaterialSupplier.is_active)))
    graph = bom_service._load_graph(db)
    for sku, vehicle_id in demo_ids["vehicles"].items():
        parts = bom_service.explode(db, vehicle_id, 1, graph=graph)
        assert parts, f"{sku} has no purchased parts"
        missing = [m for m in parts if m not in linked]
        assert not missing, f"{sku}: purchased parts without a supplier: {missing}"


def test_sokratescar_is_sourced_only_from_pt_fandi_and_pt_chris(db, demo_ids):
    parts = bom_service.explode(db, demo_ids["vehicles"]["FG-SDN-SKR-21"], 1)
    codes = set(db.scalars(select(Supplier.code).join(MaterialSupplier, MaterialSupplier.supplier_id == Supplier.id)
                           .where(MaterialSupplier.material_id.in_(list(parts)))))
    assert codes == {"SUP-FND", "SUP-CHR"}


def test_demo_schedules_plan_and_every_shortfall_has_a_supplier(db, demo_ids):
    schedules = list(db.scalars(select(Schedule).order_by(Schedule.production_date)))
    assert [s.target_qty for s in schedules] == [30, 20, 10]
    first, last = schedules[0].production_date, schedules[-1].production_date
    run = planning_service.run_planning(db, first, last + timedelta(days=1))
    short = [line for line in run.lines if line.shortfall > 0]
    linked = set(db.scalars(select(MaterialSupplier.material_id)))
    assert run.lines and all(line.material_id in linked for line in short)
    assert first >= date.today() - timedelta(days=6)


def test_seed_refuses_a_database_that_already_has_data(db, demo_ids):
    with pytest.raises(RuntimeError):
        demo.seed(db)


def test_api_serves_the_demo_catalogue(client, db, demo_ids):
    products = client.get("/api/v1/products").json()
    names = {p["name"] for p in (products["items"] if isinstance(products, dict) else products)}
    assert "Compact Electric SUV 60 kWh" in names and len(names) == 21
