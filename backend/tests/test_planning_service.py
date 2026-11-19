"""Golden test tabel 2.2 / Phase 2 spesifikasi (Senin 30 + Selasa 20 = 50 unit)."""
from datetime import date

import pytest

from app.core.exceptions import AppError
from app.services import schedule_service
from app.models.enums import StockStatus
from app.services import planning_service as ps


@pytest.fixture()
def planned(db, seeded):
    schedule_service.create_schedule(db, seeded["BIKE"], date(2026, 10, 12), 30)   # lewat service: batch + allocated
    schedule_service.create_schedule(db, seeded["BIKE"], date(2026, 10, 13), 20)
    return ps.run_planning(db, date(2026, 10, 12), date(2026, 10, 13))


def _by_sku(run):
    return {l.material.sku: l for l in run.lines}


def test_golden_table(planned):
    L = _by_sku(planned)
    expect = {  # sku: (gross, on_hand, allocated, available, safety, shortfall, status)
        "RM-RUB-01": (100, 80, 100, -20, 40, 60, StockStatus.CRITICAL),
        "RM-SBR-01": (50, 50, 50, 0, 15, 15, StockStatus.CRITICAL),
        "RM-STEEL-01": (75, 100, 75, 25, 50, 25, StockStatus.WARNING),
        "RM-PDL-01": (100, 120, 100, 20, 30, 10, StockStatus.WARNING),
    }
    for sku, (g, oh, al, av, ss, sf, st) in expect.items():
        l = L[sku]
        assert (l.gross_requirement, l.on_hand, l.allocated, l.available,
                l.safety_stock, l.shortfall, l.status) == (g, oh, al, av, ss, sf, st), sku
    assert L["RM-RUB-01"].needed_by == date(2026, 10, 12)
    # material lain aman
    others = [l for s, l in L.items() if s not in expect]
    assert others and all(l.status == StockStatus.SAFE and l.shortfall == 0 for l in others)


def test_available_formula_and_allocation_idempotent(db, seeded, planned):
    first = {l.material.sku: l.allocated for l in planned.lines}
    again = ps.run_planning(db, date(2026, 10, 12), date(2026, 10, 13))
    assert {l.material.sku: l.allocated for l in again.lines} == first   # di-overwrite, bukan akumulasi
    from app.models import Inventory
    inv = db.get(Inventory, 1)
    assert inv.available == inv.on_hand - inv.allocated


def test_no_schedule_is_400(db, seeded):
    with pytest.raises(AppError) as e:
        ps.run_planning(db, date(2026, 1, 1), date(2026, 1, 2))
    assert e.value.status_code == 400


def test_classify_thresholds():
    assert ps.classify(0, 10) == StockStatus.CRITICAL
    assert ps.classify(-5, 10) == StockStatus.CRITICAL
    assert ps.classify(9.99, 10) == StockStatus.WARNING
    assert ps.classify(10, 10) == StockStatus.SAFE
