"""Query budget for list endpoints: the number of SQL statements must not grow with the number of rows.

On SAP BTP the database (Supabase) is ~140 ms away, so an N+1 loop over 36 suppliers costs ~25-45 s per page.
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
             "/api/v1/hub/approvals", "/api/v1/purchase-orders", "/api/v1/activity"]


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


def _costs(client) -> dict[str, int]:
    out = {}
    for url in ENDPOINTS:
        with count_queries() as c:
            r = client.get(url)
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
