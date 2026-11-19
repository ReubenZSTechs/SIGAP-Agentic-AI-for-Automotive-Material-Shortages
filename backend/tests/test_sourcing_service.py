from datetime import date

import pytest

from app.core.exceptions import AppError
from app.models import MaterialSupplier
from app.services import schedule_service
from app.models.enums import SourcingStrategy
from app.services import planning_service as ps
from app.services import sourcing_service as ss


@pytest.fixture()
def run(db, seeded):
    schedule_service.create_schedule(db, seeded["BIKE"], date(2026, 10, 12), 30)   # lewat service: batch + allocated
    schedule_service.create_schedule(db, seeded["BIKE"], date(2026, 10, 13), 20)
    return ps.run_planning(db, date(2026, 10, 12), date(2026, 10, 13))


def _line(run, sku):
    return next(l for l in run.lines if l.material.sku == sku)


def test_cheapest_vs_fastest_differ_on_pedal(db, run):
    line = _line(run, "RM-PDL-01")
    cheapest = ss.recommend(db, line, SourcingStrategy.CHEAPEST)
    fastest = ss.recommend(db, line, SourcingStrategy.FASTEST)
    assert cheapest[0]["supplier_name"] == "CV Makmur Bersama"       # Rp 42.500
    assert fastest[0]["supplier_name"] == "PT Industri Lokal"        # 2 hari
    assert cheapest[0]["is_cheapest"] and fastest[0]["is_fastest"]
    assert [o["rank"] for o in cheapest] == [1, 2, 3]
    assert len(cheapest) == 3


def test_steel_and_rubber_recommendations(db, run):
    steel = ss.recommend(db, _line(run, "RM-STEEL-01"), SourcingStrategy.FASTEST)
    assert steel[0]["supplier_name"] == "CV Cipta Logam" and steel[0]["lead_time_days"] == 4
    rub = ss.recommend(db, _line(run, "RM-RUB-01"), SourcingStrategy.CHEAPEST)
    assert rub[0]["supplier_name"] == "PT Karet Nusantara" and rub[0]["suggested_qty"] == 60
    assert rub[0]["est_total"] == 60 * 35000


def test_balanced_returns_ranked_options(db, run):
    opts = ss.recommend(db, _line(run, "RM-PDL-01"), SourcingStrategy.BALANCED)
    assert len(opts) == 3 and opts[0]["rank"] == 1


def test_moq_above_shortfall_raises_suggested_qty(db, run):
    line = _line(run, "RM-PDL-01")                                    # defisit 10
    link = next(l for l in line.material.supplier_links if l.supplier.code == "SUP-MKM")
    link.moq = 25
    db.commit()
    opts = ss.recommend(db, line, SourcingStrategy.CHEAPEST, respect_moq=False)
    makmur = next(o for o in opts if o["supplier_name"] == "CV Makmur Bersama")
    assert makmur["suggested_qty"] == 25 and makmur["meets_moq"] is False
    assert makmur["est_total"] == 25 * 42500
    # respect_moq=True menyaring yang tidak memenuhi MOQ (karena masih ada yang memenuhi)
    strict = ss.recommend(db, line, SourcingStrategy.CHEAPEST, respect_moq=True)
    assert "CV Makmur Bersama" not in [o["supplier_name"] for o in strict]


def test_max_lead_days_filter(db, run):
    opts = ss.recommend(db, _line(run, "RM-PDL-01"), SourcingStrategy.CHEAPEST, max_lead_days=3)
    assert {o["supplier_name"] for o in opts} == {"PT Industri Lokal", "PT Mitra Komponen"}


def test_select_supplier_validations(db, seeded, run):
    line = _line(run, "RM-PDL-01")
    with pytest.raises(AppError) as e:                                # supplier bukan relasi material
        ss.select_supplier(db, line, seeded["KARET"])
    assert e.value.status_code == 400
    with pytest.raises(AppError) as e:                                # qty < defisit
        ss.select_supplier(db, line, seeded["INDUSTRI"], 5)
    assert e.value.status_code == 400
    ss.select_supplier(db, line, seeded["INDUSTRI"])                  # default = max(defisit, moq)
    assert line.order_qty == 10 and line.unit_price == 48000 and line.lead_time_days == 2


def test_auto_select_picks_rank1_for_unselected(db, run):
    selected, skipped = ss.auto_select(db, run, SourcingStrategy.CHEAPEST)
    assert len(selected) == 4 and skipped == []
    assert _line(run, "RM-PDL-01").selected_supplier_id is not None


def test_no_supplier_yields_empty_options(db, seeded, run):
    line = _line(run, "RM-PDL-01")
    db.query(MaterialSupplier).filter_by(material_id=line.material_id).delete()
    db.commit()
    db.expire_all()
    assert ss.recommend(db, line) == []
