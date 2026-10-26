"""Supplier choice for purchase orders: which supplier link to use for each material."""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Material, Supplier
from app.services import master_service
from configs.tools.po_common import rupiah


# ------------------------------------ supplier choice ------------------------------------
def active_links(db: Session, material_id: int) -> list[dict]:
    """`master_service.list_links` rows usable for ordering: active link AND active supplier."""
    active_suppliers = set(db.scalars(select(Supplier.id).where(Supplier.is_active)))
    return [l for l in master_service.list_links(db, material_id)
            if l["is_active"] and l["supplier_id"] in active_suppliers]


def pick_supplier(links: list[dict], qty: float, exclude_supplier_id: int | None = None) -> dict | None:
    """Chooses the supplier link to propose for `qty` units of one material.

    Used for new PO proposals (no supplier named by the user) and for re-sourcing after a
    supplier revision (`exclude_supplier_id` = the current supplier).

    `links`: rows from `active_links()` with keys supplier_id, supplier_code, supplier_name,
    unit_price, lead_time_days, moq, is_preferred, is_cheapest, is_fastest.
    Returns the chosen link, or None when no link is acceptable.
    """
    candidates = [l for l in links if l["supplier_id"] != exclude_supplier_id]
    if not candidates:
        return None
    # Utamakan supplier yang MOQ-nya terpenuhi; bila tidak ada, tetap usulkan (resolver menambah peringatan MOQ).
    within_moq = [l for l in candidates if qty >= l["moq"]] or candidates
    # Preferred dulu (kontrak/kesepakatan pembelian), lalu termurah, lalu tercepat, lalu kode (deterministik).
    return min(within_moq, key=lambda l: (not l["is_preferred"], l["unit_price"], l["lead_time_days"],
                                          l["supplier_code"]))


def pick_replacement(links: list[dict], qty: float, arrive_by: date | None, exclude_supplier_id: int,
                     today: date | None = None) -> tuple[dict | None, bool]:
    """Replacement supplier after a supplier cancels / is too late: (link, arrives_in_time).

    Among MOQ-feasible active links of OTHER suppliers: those arriving by `arrive_by` (today + lead time),
    cheapest first (then fastest, preferred, code); when none is in time, the fastest one (flagged late).
    """
    today = today or date.today()
    candidates = [l for l in links if l["supplier_id"] != exclude_supplier_id]
    if not candidates:
        return None, False
    candidates = [l for l in candidates if qty >= l["moq"]] or candidates
    in_time = [l for l in candidates if arrive_by is None or today + timedelta(days=l["lead_time_days"]) <= arrive_by]
    if in_time:
        return min(in_time, key=lambda l: (l["unit_price"], l["lead_time_days"], not l["is_preferred"],
                                           l["supplier_code"])), True
    return min(candidates, key=lambda l: (l["lead_time_days"], l["unit_price"], l["supplier_code"])), False


def assign_suppliers(db: Session, needs: list[dict], deadline: date | None = None, today: date | None = None,
                     order_qty=None) -> dict:
    """Chooses one supplier per material, cross-checked over ALL materials so that fewer POs are needed.

    `needs`: [{material_id, sku, name, uom, qty}]. With `deadline`, only links that can arrive in time
    (today + lead time <= deadline) are candidates; a material nobody can deliver in time gets its
    fastest link and a warning. `order_qty(need, link)` gives the quantity ordered from a link
    (default: the needed qty).

    Greedy cover: repeatedly take the supplier that can supply the most still-unassigned materials
    (ties: fewer MOQ shortfalls, more preferred links, lower cost, shorter lead time, code), assign
    those materials to it, repeat. One supplier that sells several of the materials therefore gets
    them all on one PO, even when another supplier is a little cheaper for one of them.

    Returns {assigned: [(link, need, qty, late)], missing: [need], warnings: [...],
    extra_cost: consolidated cost - cheapest-per-material cost, saved_pos: POs avoided}.
    """
    today = today or date.today()
    order_qty = order_qty or (lambda need, link: need["qty"])
    cands, late, missing, warnings = {}, set(), [], []
    for n, need in enumerate(needs):
        links = active_links(db, need["material_id"])
        if not links:
            missing.append(need)
            continue
        ok = [l for l in links if deadline is None or today + timedelta(days=l["lead_time_days"]) <= deadline]
        if not ok:
            fastest = min(links, key=lambda l: (l["lead_time_days"], l["unit_price"], l["supplier_code"]))
            ok, earliest = [fastest], today + timedelta(days=fastest["lead_time_days"])
            late.add(n)
            warnings.append(f"{need['name']}: {fastest['supplier_name']} paling cepat tiba {earliest.isoformat()} "
                            f"(setelah {deadline.isoformat()})")
        cands[n] = {l["supplier_id"]: l for l in ok}

    def cost(n, link):
        return order_qty(needs[n], link) * link["unit_price"]

    unassigned, assigned, chosen_cost = set(cands), [], 0
    while unassigned:
        suppliers = {sid for n in unassigned for sid in cands[n]}

        def score(sid):
            covered = [n for n in unassigned if sid in cands[n]]
            links = [cands[n][sid] for n in covered]
            return (-len(covered), sum(needs[n]["qty"] < l["moq"] for n, l in zip(covered, links)),
                    -sum(l["is_preferred"] for l in links), sum(cost(n, cands[n][sid]) for n in covered),
                    max(l["lead_time_days"] for l in links), links[0]["supplier_code"])
        best = min(suppliers, key=score)
        for n in sorted(n for n in unassigned if best in cands[n]):
            link = cands[n][best]
            assigned.append((link, needs[n], order_qty(needs[n], link), n in late))
            chosen_cost += cost(n, link)
            unassigned.discard(n)
    cheapest = sum(min(cost(n, l) for l in cands[n].values()) for n in cands)
    cheapest_suppliers = {min(cands[n].values(), key=lambda l: (cost(n, l), l["supplier_code"]))["supplier_id"]
                          for n in cands}
    used = {a[0]["supplier_id"] for a in assigned}
    return {"assigned": assigned, "missing": missing, "warnings": warnings,
            "extra_cost": round(chosen_cost - cheapest), "saved_pos": max(0, len(cheapest_suppliers) - len(used))}


def consolidation_note(result: dict) -> str | None:
    if result["saved_pos"] <= 0:
        return None
    extra = result["extra_cost"]
    cost = f"+{rupiah(extra)} dibanding pemasok termurah per material, " if extra > 0 else ""
    return f"Material digabung per supplier: {cost}hemat {result['saved_pos']} PO."


def _line(link: dict, material: Material | dict, qty: float, needed_by: str | None) -> dict:
    m = material if isinstance(material, dict) else {"material_id": material.id, "sku": material.sku,
                                                       "name": material.name, "uom": material.uom}
    return {**{k: m[k] for k in ("material_id", "sku", "name", "uom")},
            "qty_ordered": qty, "unit_price": link["unit_price"], "line_total": round(qty * link["unit_price"]),
            "lead_time_days": link["lead_time_days"], "moq": link["moq"], "needed_by_date": needed_by}


def _group_by_supplier(db: Session, lines: list[tuple[dict, dict]]) -> list[dict]:
    """[(link, line)] -> one PO proposal per supplier (like `po_service.generate_pos`)."""
    groups: dict[int, list] = defaultdict(list)
    links = {}
    for link, line in lines:
        groups[link["supplier_id"]].append(line)
        links[link["supplier_id"]] = link
    out = []
    for sid, items in groups.items():
        sup = db.get(Supplier, sid)
        out.append({"supplier_id": sid, "supplier_code": sup.code, "supplier_name": sup.name,
                    "payment_term_days": sup.payment_term_days, "items": items,
                    "total_amount": sum(i["line_total"] for i in items)})
    return out


def payment_schedule(groups: list[dict], today: date | None = None) -> dict:
    """When each supplier must be paid, before the POs are sent (one row per supplier, earliest first).

    Expected arrival = today + the longest lead time of the supplier's lines. Pay by = arrival + payment term
    (Net N days); Net 0 (cash) = pay on arrival. Returns {rows, total, last_pay_by, latest_arrival}.
    """
    today = today or date.today()
    rows = []
    for g in groups:
        arrival = today + timedelta(days=max((i.get("lead_time_days") or 0) for i in g["items"]))
        term = g.get("payment_term_days") or 0
        rows.append({"supplier_name": g["supplier_name"], "materials": ", ".join(i["name"] for i in g["items"]),
                     "amount": g["total_amount"], "payment_term_days": term,
                     "arrival_date": arrival.isoformat(), "pay_by": (arrival + timedelta(days=term)).isoformat()})
    rows.sort(key=lambda r: (r["pay_by"], r["supplier_name"]))
    return {"rows": rows, "total": sum(r["amount"] for r in rows),
            "last_pay_by": max((r["pay_by"] for r in rows), default=None),
            "latest_arrival": max((r["arrival_date"] for r in rows), default=None)}


def earliest_arrival(db: Session, material_id: int, today: date) -> date | None:
    """The soonest a material can arrive: today + the shortest lead time among its active suppliers."""
    links = active_links(db, material_id)
    return today + timedelta(days=min(l["lead_time_days"] for l in links)) if links else None
