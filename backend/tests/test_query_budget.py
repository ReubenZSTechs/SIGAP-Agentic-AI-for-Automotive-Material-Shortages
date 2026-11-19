"""Query budget for list endpoints: the number of SQL statements must not grow with the number of rows.

On SAP BTP the database (AWS RDS us-east-1) is ~140-200 ms away, so an N+1 loop over 36 suppliers costs ~25-45 s
per page.
These tests count statements with few vs. many suppliers/missions/POs and fail when a page scales per row.
"""
import contextlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app.database import SessionLocal, engine
from app.models import PurchaseOrder, Supplier
from configs.tools import po_actions as A
from tests import po_helpers as H

ENDPOINTS = ["/api/v1/hub/status", "/api/v1/hub/suppliers", "/api/v1/hub/threads", "/api/v1/hub/missions",
             "/api/v1/hub/approvals", "/api/v1/hub/mission-options", "/api/v1/hub/audit", "/api/v1/hub/manager/messages",
             "/api/v1/purchase-orders", "/api/v1/activity", "/api/v1/activity/facets", "/api/v1/suppliers"]
# Master-data pages (materials, products, BOM, stock, MPS, planning); {latest} = newest planning run id.
MASTER_ENDPOINTS = ["/api/v1/materials", "/api/v1/products", "/api/v1/suppliers", "/api/v1/inventory",
                    "/api/v1/stock-movements", "/api/v1/production-lines", "/api/v1/schedules", "/api/v1/bom/{bike}/tree",
                    "/api/v1/bom/{bike}/explosion", "/api/v1/materials/{rub}/suppliers", "/api/v1/planning/runs",
                    "/api/v1/planning/runs/{latest}", "/api/v1/planning/runs/{latest}/lines",
                    "/api/v1/planning/runs/{latest}/sourcing", "/api/v1/hub/mission-options"]


@contextlib.contextmanager
def count_queries():
    counter = {"n": 0}

    def before(conn, cursor, statement, params, context, executemany):
        counter["n"] += 1
    event.listen(engine, "before_cursor_execute", before)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", before)


def _populate(seeded, n: int, start: int = 0) -> None:
    """n extra suppliers, each linked to Telegram (sandbox), with a message thread, an issued PO with an open
    conversation (-> a PO mission) and a Hub price-quote mission target."""
    from app.supplier_chat.transport import sandbox_chat_id
    from app.models import HubMission, HubMissionTarget, SupplierMessage, SupplierTelegramLink
    from app.models.enums import MessageDirection
    from app.models.hub import MissionScenario, MissionStatus, TargetState
    rub = seeded["materials"]["RM-RUB-01"]
    with SessionLocal() as db:
        for i in range(start, start + n):
            sup = Supplier(code=f"SUP-Q{i:02d}", name=f"Query Test Supplier {i}", payment_term_days=30,
                           contact=f"Contact {i} | +62 21 {i:04d}")
            db.add(sup)
            db.flush()
            db.add(SupplierTelegramLink(supplier_id=sup.id, chat_id=sandbox_chat_id(sup.id), link_token=f"tok{i}x{sup.id}",
                                        linked_at=datetime.now(timezone.utc).replace(tzinfo=None)))
            db.add_all([SupplierMessage(supplier_id=sup.id, chat_id=sandbox_chat_id(sup.id), direction=d, text=f"m{k}")
                        for k, d in enumerate([MessageDirection.OUT, MessageDirection.IN, MessageDirection.OUT])])
            m = HubMission(scenario=MissionScenario.PRICE_QUOTE, title=f"Quote {i}", items=[], message_template="x",
                           deadline=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=2),
                           status=MissionStatus.ACTIVE, created_by="Tester")
            m.targets = [HubMissionTarget(supplier_id=sup.id, state=TargetState.SENT)]
            db.add(m)
            db.commit()
            with A.write_session() as wdb:
                po = A.create_and_issue_po(wdb, {"supplier_id": sup.id, "items": [
                    {"material_id": rub, "qty_ordered": 5, "unit_price": 1000, "needed_by_date": None}]}, "Tester")
                A.queue_conversation(wdb, po, A.ConversationPurpose.CONFIRM_ORDER)


def _populate_master(seeded, n: int, start: int = 0) -> None:
    """n extra purchased materials (stock + 2 suppliers each), each used by a new finished product that is also a
    component of the bike, with one production schedule per product, then a fresh planning run."""
    from datetime import date
    from app.models import BOMItem, Inventory, Material, MaterialSupplier
    from app.models.enums import ItemCategory
    from app.services import planning_service, schedule_service
    with SessionLocal() as db:
        for i in range(start, start + n):
            rm = Material(sku=f"RM-Q{i:02d}", name=f"Query Material {i}", uom="pcs", category=ItemCategory.PURCHASED)
            fg = Material(sku=f"FG-Q{i:02d}", name=f"Query Product {i}", uom="unit", category=ItemCategory.FINISHED,
                          selling_price=100_000)
            db.add_all([rm, fg])
            db.flush()
            db.add(Inventory(material_id=rm.id, on_hand=5, allocated=0, safety_stock=10))
            db.add_all([MaterialSupplier(material_id=rm.id, supplier_id=seeded[s], unit_price=1000 + i, lead_time_days=3,
                                         moq=1) for s in ("KARET", "CIPTA")])
            db.add_all([BOMItem(parent_id=fg.id, child_id=rm.id, qty_per_parent=2),
                        BOMItem(parent_id=seeded["BIKE"], child_id=rm.id, qty_per_parent=1)])
            db.commit()
            schedule_service.create_schedule(db, fg.id, date.today() + timedelta(days=7 + i), 10, seeded["LINE1"])
        planning_service.run_planning(db, date.today(), date.today() + timedelta(days=60))


def _costs(client, endpoints=ENDPOINTS, ids: dict | None = None) -> dict[str, int]:
    out = {}
    for url in endpoints:
        with count_queries() as c:
            r = client.get(url.format(**(ids or {})))
        assert r.status_code == 200, (url, r.text)
        out[url] = c["n"]
    return out


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_list_endpoints_do_not_scale_with_rows(client, seeded, endpoint):
    _populate(seeded, 3)
    small = _costs(client)[endpoint]
    _populate(seeded, 12, start=3)                           # 5x more suppliers, POs, missions, threads
    big = _costs(client)[endpoint]
    assert big - small <= 2, f"{endpoint}: {small} queries with 3 suppliers, {big} with 15 (N+1)"
    assert big <= 25, f"{endpoint}: {big} queries"


@pytest.mark.parametrize("endpoint", MASTER_ENDPOINTS)
def test_master_pages_do_not_scale_with_rows(client, seeded, endpoint):
    def ids():
        latest = client.get("/api/v1/planning/runs").json()[0]["id"]
        return {"bike": seeded["BIKE"], "rub": seeded["materials"]["RM-RUB-01"], "latest": latest}
    _populate_master(seeded, 3)
    small = _costs(client, [endpoint], ids())[endpoint]
    _populate_master(seeded, 12, start=3)                    # 5x more materials, products, BOM rows, schedules
    big = _costs(client, [endpoint], ids())[endpoint]
    assert big - small <= 2, f"{endpoint}: {small} queries with 3 extra materials, {big} with 15 (N+1)"
    assert big <= 25, f"{endpoint}: {big} queries"
