"""Production costing for the chatbot: what does it cost to make N units, and what profit is left?

Read-only. The numbers are computed here (never by the LLM) so the answer can quote them exactly.

    1. explode the BOM         -> how much of each purchased material N units need
    2. choose a supplier       -> per material, by strategy (cheapest / preferred / fastest / most expensive),
                                  MOQ respected; each line also shows the cheapest vs most expensive offer
    3. add up                  -> material cost, revenue, gross profit

Profit = selling price x qty - cost of buying every purchased material. Labour and overhead are not in the
data, so they are not included (the result says so).
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import Material
from app.services import bom_service
from configs.tools.po_sourcing import active_links, pick_supplier

STRATEGIES = ("CHEAPEST", "PREFERRED", "FASTEST", "MOST_EXPENSIVE")
EXCLUDES = "biaya tenaga kerja & overhead (tidak ada di data)"


def order_quantity(required: float, link: dict) -> float:
    """A supplier sells at least its MOQ, so a small need is rounded up to the MOQ."""
    return max(required, link["moq"])


def link_cost(required: float, link: dict) -> float:
    return order_quantity(required, link) * link["unit_price"]


def arrival_date(link: dict, today: date) -> date:
    return today + timedelta(days=link["lead_time_days"])


def in_time(links: list[dict], deadline: date | None, today: date) -> list[dict]:
    """Links that arrive by the deadline (all links when there is no deadline)."""
    if deadline is None:
        return links
    return [l for l in links if arrival_date(l, today) <= deadline]


def cheapest_link(links: list[dict], required: float) -> dict:
    return min(links, key=lambda l: (link_cost(required, l), l["lead_time_days"], l["supplier_code"]))


def most_expensive_link(links: list[dict], required: float) -> dict:
    return max(links, key=lambda l: (link_cost(required, l), -l["lead_time_days"], l["supplier_code"]))


def fastest_link(links: list[dict], required: float) -> dict:
    return min(links, key=lambda l: (l["lead_time_days"], link_cost(required, l), l["supplier_code"]))


def choose_link(links: list[dict], required: float, strategy: str, deadline: date | None,
                today: date) -> tuple[dict | None, bool]:
    """The supplier link for one material. Returns (link or None, late).

    With a `deadline`, only links that arrive in time are considered; if none can, the fastest link is
    used and the line is marked late.
    """
    if not links:
        return None, False
    candidates = in_time(links, deadline, today)
    if not candidates:
        return fastest_link(links, required), True
    if strategy == "FASTEST":
        return fastest_link(candidates, required), False
    if strategy == "PREFERRED":
        return pick_supplier(candidates, required), False
    if strategy == "MOST_EXPENSIVE":
        return most_expensive_link(candidates, required), False
    return cheapest_link(candidates, required), False


def material_lines(db: Session, product: Material, qty: float, strategy: str, deadline: date | None,
                   today: date) -> list[dict]:
    """One line per purchased material needed for `qty` units, with the chosen supplier and its cost."""
    needs = bom_service.explode(db, product.id, qty)           # {material_id: required qty}
    lines = []
    for material_id, required in needs.items():
        m = db.get(Material, material_id)
        links = active_links(db, material_id)
        link, late = choose_link(links, required, strategy, deadline, today)
        line = {"material_name": m.name, "material_sku": m.sku, "required_qty": required, "uom": m.uom,
                "supplier_name": None, "unit_price": None, "moq": None, "order_qty": None, "cost": None,
                "lead_time_days": None, "arrival_date": None, "late": False,
                "supplier_count": len(links), "cheapest_supplier": None, "cheapest_cost": None,
                "most_expensive_supplier": None, "most_expensive_cost": None, "cost_difference": None}
        if link is not None:
            line.update(supplier_name=link["supplier_name"], unit_price=link["unit_price"], moq=link["moq"],
                        order_qty=order_quantity(required, link), cost=round(link_cost(required, link)),
                        lead_time_days=link["lead_time_days"], arrival_date=arrival_date(link, today), late=late)
            # perbandingan antar supplier untuk material ini (yang tiba tepat waktu, bila ada tenggat)
            options = in_time(links, deadline, today) or links
            low, high = cheapest_link(options, required), most_expensive_link(options, required)
            line.update(cheapest_supplier=low["supplier_name"], cheapest_cost=round(link_cost(required, low)),
                        most_expensive_supplier=high["supplier_name"],
                        most_expensive_cost=round(link_cost(required, high)),
                        cost_difference=round(link_cost(required, high) - link_cost(required, low)))
        lines.append(line)
    return sorted(lines, key=lambda l: l["material_name"])


def estimate(db: Session, product: Material, qty: float, strategy: str = "CHEAPEST", deadline: date | None = None,
             today: date | None = None) -> tuple[list[dict], dict]:
    """(material lines, summary) for producing `qty` units of `product` with the given supplier strategy."""
    today = today or date.today()
    strategy = strategy if strategy in STRATEGIES else "CHEAPEST"
    lines = material_lines(db, product, qty, strategy, deadline, today)
    cost = sum(l["cost"] for l in lines if l["cost"] is not None)
    revenue = round((product.selling_price or 0) * qty)
    profit = revenue - cost
    arrivals = [l["arrival_date"] for l in lines if l["arrival_date"]]
    summary = {
        "product_name": product.name, "qty": qty, "strategy": strategy,
        "needed_by_date": deadline, "selling_price": product.selling_price or 0,
        "revenue": revenue, "total_material_cost": cost, "gross_profit": profit,
        "profit_per_unit": round(profit / qty) if qty else 0,
        "margin_pct": round(profit / revenue * 100, 1) if revenue else None,
        "slowest_arrival_date": max(arrivals) if arrivals else None,
        "materials_without_supplier": [l["material_name"] for l in lines if l["supplier_name"] is None],
        "late_materials": [l["material_name"] for l in lines if l["late"]],
        "excludes": EXCLUDES,
    }
    return lines, summary


def compare_strategies(db: Session, product: Material, qty: float, deadline: date | None = None,
                       today: date | None = None) -> dict:
    """Material cost and profit for EVERY strategy, so one call answers "termurah vs termahal" questions.

    CHEAPEST gives the maximum profit, MOST_EXPENSIVE the minimum.
    """
    costs, profits = {}, {}
    for strategy in STRATEGIES:
        _, summary = estimate(db, product, qty, strategy, deadline, today)
        costs[strategy] = summary["total_material_cost"]
        profits[strategy] = summary["gross_profit"]
    return {"cost_by_strategy": costs, "profit_by_strategy": profits,
            "max_profit": profits["CHEAPEST"], "min_profit": profits["MOST_EXPENSIVE"],
            "profit_difference_cheapest_vs_most_expensive": profits["CHEAPEST"] - profits["MOST_EXPENSIVE"]}


def compare_links(links: list[dict], qty: float, today: date | None = None) -> list[dict]:
    """Suppliers of ONE material compared for buying `qty` units (MOQ-aware), cheapest total first."""
    today = today or date.today()
    rows = [{**l, "order_qty": order_quantity(qty, l), "total_cost": round(link_cost(qty, l)),
             "arrival_date": arrival_date(l, today)} for l in links]
    rows.sort(key=lambda r: (r["total_cost"], r["lead_time_days"], r["supplier_code"]))
    cheapest = rows[0]["total_cost"] if rows else 0
    for r in rows:
        r["difference_vs_cheapest"] = r["total_cost"] - cheapest
    return rows
