"""Production profit and supplier comparison tools (numbers computed by code, never by the LLM)."""
from datetime import date, timedelta

from app.chatbot.evidence import make_evidence, render_table
from configs.tools.registry import run_curated
from tests.spec_seed import BOM, SOURCING


def _leaf_needs(qty: float) -> dict[str, float]:
    """Purchased-material needs of `qty` bikes, computed from the seed BOM (independent of the app code)."""
    children = {}
    for parent, child, q in BOM:
        children.setdefault(parent, []).append((child, q))
    needs = {}

    def walk(sku, mult):
        if sku not in children:
            needs[sku] = needs.get(sku, 0) + mult
            return
        for child, q in children[sku]:
            walk(child, mult * q)

    walk("FG-BIKE-01", qty)
    return needs


def _cost(qty: float, pick=min) -> int:
    """Material cost of `qty` bikes when each material is bought from the cheapest (min) or most
    expensive (max) supplier, MOQ respected."""
    return round(sum(pick(max(need, moq) * price for _, price, _, moq in SOURCING[sku])
                     for sku, need in _leaf_needs(qty).items()))


def _cheapest_cost(qty: float) -> int:
    return _cost(qty, min)


def test_cheapest_production_profit_for_100_bikes(seeded):
    ev = run_curated("estimate_production_profit", {"product": "Sepeda Gunung", "qty": 100}, "", "E1", 200)
    meta = ev["meta"]
    assert ev["error"] is None and ev["row_count"] == len(_leaf_needs(100))
    assert meta["strategy"] == "CHEAPEST" and meta["revenue"] == 450_000_000
    assert meta["total_material_cost"] == _cheapest_cost(100)
    assert meta["gross_profit"] == 450_000_000 - _cheapest_cost(100)
    assert meta["cost_by_strategy"]["CHEAPEST"] == meta["total_material_cost"]
    assert meta["cost_by_strategy"]["FASTEST"] >= meta["cost_by_strategy"]["CHEAPEST"]
    assert meta["materials_without_supplier"] == [] and "tenaga kerja" in meta["excludes"]
    pedal = next(r for r in ev["rows"] if r["material_name"] == "Pedal Sepeda")
    assert pedal["supplier_name"] == "CV Makmur Bersama" and pedal["unit_price"] == 42500


def test_moq_rounds_small_needs_up(seeded):
    ev = run_curated("estimate_production_profit", {"product": "Sepeda Gunung", "qty": 1}, "", "E1", 200)
    screws = next(r for r in ev["rows"] if r["material_name"] == "Baut Bintang / Torx Screw M6")
    assert screws["required_qty"] == 20 and screws["order_qty"] == 100 and screws["cost"] == 100 * 500


def test_deadline_marks_late_materials(seeded):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    ev = run_curated("estimate_production_profit", {"product": "Sepeda Gunung", "qty": 10, "date_to": tomorrow},
                     "", "E1", 200)
    rubber = next(r for r in ev["rows"] if r["material_name"] == "Ban Luar Karet")
    assert rubber["supplier_name"] == "CV Rubber Indonesia" and rubber["late"] is False   # 1 hari: tepat waktu
    assert "Pedal Sepeda" in ev["meta"]["late_materials"]


def test_compare_suppliers_of_one_material(seeded):
    ev = run_curated("get_material_suppliers", {"material": "Pedal Sepeda", "qty": 50}, "", "E1", 200)
    rows, meta = ev["rows"], ev["meta"]
    assert [r["supplier_name"] for r in rows] == ["CV Makmur Bersama", "PT Mitra Komponen", "PT Industri Lokal"]
    assert [r["total_cost"] for r in rows] == [2_125_000, 2_250_000, 2_400_000]
    assert [r["difference_vs_cheapest"] for r in rows] == [0, 125_000, 275_000]
    assert meta["cheapest_supplier"] == "CV Makmur Bersama" and meta["fastest_supplier"] == "PT Industri Lokal"


def test_tables_show_names_not_codes():
    ev = make_evidence("E1", "t", {}, "", [{"sku": "RM-RUB-01", "name": "Ban Luar Karet", "supplier_code": "SUP-KRT",
                                            "supplier_name": "PT Karet Nusantara", "unit_price": 35000}], row_limit=10)
    table = render_table(ev, ["sku", "supplier_code", "unit_price"], "id")
    assert table["columns"] == ["Nama", "Supplier", "Harga Satuan"]
    assert table["rows"][0][:2] == ["Ban Luar Karet", "PT Karet Nusantara"]


def test_cheapest_vs_most_expensive_in_one_call(seeded):
    ev = run_curated("estimate_production_profit", {"product": "sepeda gunung", "qty": 100}, "", "E1", 200)
    meta = ev["meta"]
    assert set(meta["profit_by_strategy"]) == {"CHEAPEST", "PREFERRED", "FASTEST", "MOST_EXPENSIVE"}
    assert meta["cost_by_strategy"]["MOST_EXPENSIVE"] == _cost(100, max)
    assert meta["max_profit"] == 450_000_000 - _cost(100, min)
    assert meta["min_profit"] == 450_000_000 - _cost(100, max)
    assert meta["profit_difference_cheapest_vs_most_expensive"] == _cost(100, max) - _cost(100, min)
    pedal = next(r for r in ev["rows"] if r["material_name"] == "Pedal Sepeda")
    assert (pedal["cheapest_supplier"], pedal["most_expensive_supplier"]) == ("CV Makmur Bersama", "PT Industri Lokal")
    assert pedal["cost_difference"] == 200 * (48000 - 42500)   # 2 pedal per sepeda and pedal["supplier_count"] == 3


def test_most_expensive_strategy_rows(seeded):
    ev = run_curated("estimate_production_profit",
                     {"product": "Sepeda Gunung", "qty": 100, "strategy": "MOST_EXPENSIVE"}, "", "E1", 200)
    assert ev["meta"]["total_material_cost"] == _cost(100, max)
    rubber = next(r for r in ev["rows"] if r["material_name"] == "Ban Luar Karet")
    assert rubber["supplier_name"] == "CV Rubber Indonesia"


def test_unknown_product_lists_available_products(seeded):
    ev = run_curated("estimate_production_profit", {"product": "bicycles", "qty": 100}, "", "E1", 200)
    assert ev["row_count"] == 0 and ev["meta"]["available_products"] == ["Sepeda Gunung"]
