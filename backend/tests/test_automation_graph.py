"""PO automation in the Dashboard chat: clarify -> confirm (interrupt) -> execute, against the test DB."""
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.chatbot.service import ChatService
from app.database import SessionLocal
from app.models import PurchaseOrder
from configs.workflows.chat_graph import build_graph
from tests import chat_fakes as F
from tests import po_helpers as H


def _service(script: dict, calls: list | None = None):
    base = {"PromptRewriterOutput": F.REWRITE, "RouterOutput": F.ROUTE_AUTO}
    agents, fake, registry = F.fake_agents({**base, **script})
    hook = (lambda: calls.append("dispatch")) if calls is not None else None
    graph = build_graph(agents, registry.chatbot, checkpointer=InMemorySaver(), automation_cfg=registry.automation,
                        on_supplier_work=hook)
    return ChatService(graph), fake


def _action_id(final: dict) -> str:
    return next(b["actionId"] for b in final["blocks"] if b["type"] == "action")


def _pos() -> list[PurchaseOrder]:
    with SessionLocal() as db:
        ids = list(db.scalars(select(PurchaseOrder.id).order_by(PurchaseOrder.id)))
    return [H.po(i) for i in ids]


def test_ambiguous_material_is_clarified_then_proposed_and_executed(seeded):
    calls = []
    svc, fake = _service({
        "AutomationParserOutput": [F.parsed(items=[F.item("ban", 50)]), F.parsed(items=[F.item("RM-TUB-01", 50)])],
        "AutomationClarifierOutput": lambda p: F.clarify("Ban yang mana?", [
            {"label": o["label"], "value": o["value"]} for o in p["ambiguous"][0]["options"]]),
    }, calls)
    first = svc.run("Buat PO 50 ban", "thread-auto-1")
    assert first["type"] == "final" and first["meta"]["intent"] == "po_automation"
    options = next(b for b in first["blocks"] if b["type"] == "options")["options"]
    assert {o["value"] for o in options} == {"RM-RUB-01", "RM-TUB-01"}
    assert svc.pending_action("thread-auto-1") is None and _pos() == []

    second = svc.run("RM-TUB-01", "thread-auto-1")
    aid = _action_id(second)
    card = second["actions"][aid]
    assert card["kind"] == "create" and card["status"] == "pending"
    assert card["tables"][0]["rows"][0][0] == "RM-TUB-01"
    assert svc.pending_action("thread-auto-1") == aid
    assert H.action(aid).status.value == "PROPOSED" and _pos() == []

    done = svc.run(None, "thread-auto-1", {"action_id": aid, "decision": "approve"})
    assert done["type"] == "final" and done["action_updates"][aid]["status"] == "approved"
    [po] = _pos()
    assert po.status.value == "ISSUED" and po.source.value == "MANUAL" and po.items[0].qty_ordered == 50
    assert po.decided_by == "Agent MRP (dikonfirmasi pengguna)"
    [conv] = H.conversations()
    assert conv.po_id == po.id and conv.purpose.value == "CONFIRM_ORDER" and conv.status.value == "QUEUED"
    assert conv.automation_action_id == aid
    assert H.action(aid).status.value == "AWAITING_SUPPLIER" and calls == ["dispatch"]
    assert H.on_order("RM-TUB-01") == 50
    assert svc.pending_action("thread-auto-1") is None
    assert svc.actions("thread-auto-1")[aid]["status"] == "approved"


def test_reject_changes_nothing(seeded):
    svc, _ = _service({"AutomationParserOutput": F.parsed(items=[F.item("Ban Dalam", 10)])})
    aid = _action_id(svc.run("Buat PO 10 ban dalam", "thread-auto-2"))
    out = svc.run(None, "thread-auto-2", {"action_id": aid, "decision": "reject"})
    assert out["action_updates"][aid]["status"] == "rejected"
    assert _pos() == [] and H.action(aid).status.value == "REJECTED"


def test_new_message_supersedes_pending_card_and_stale_resume_is_refused(seeded):
    svc, _ = _service({"AutomationParserOutput": F.parsed(items=[F.item("Ban Dalam", 10)]),
                       "RouterOutput": [F.ROUTE_AUTO, {"intent": "smalltalk", "reason": "thanks"}],
                       "DirectResponderOutput": {"blocks": [{"type": "text", "text": "Sama-sama"}]}})
    aid = _action_id(svc.run("Buat PO 10 ban dalam", "thread-auto-3"))
    svc.run("terima kasih", "thread-auto-3")
    assert H.action(aid).status.value == "SUPERSEDED" and svc.pending_action("thread-auto-3") is None
    stale = svc.run(None, "thread-auto-3", {"action_id": aid, "decision": "approve"})
    assert stale["type"] == "error" and _pos() == []


def test_delete_draft_is_immediate(client, seeded):
    draft = H.draft_po(client, seeded, "RM-TUB-01", "SUP-KRT", 5)
    svc, _ = _service({"AutomationParserOutput": F.parsed("delete", po_reference=str(draft["id"]))})
    final = svc.run(f"Hapus PO {draft['id']}", "thread-auto-4")
    aid = _action_id(final)
    assert final["actions"][aid]["kind"] == "delete"
    svc.run(None, "thread-auto-4", {"action_id": aid, "decision": "approve"})
    assert _pos() == [] and H.action(aid).status.value == "EXECUTED"
    assert H.conversations() == []


def test_delete_issued_po_asks_the_supplier_first(seeded):
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 20)
    number = H.po(po_id).po_number
    svc, _ = _service({"AutomationParserOutput": F.parsed("delete", po_reference=number)})
    aid = _action_id(svc.run(f"Hapus {number}", "thread-auto-5"))
    svc.run(None, "thread-auto-5", {"action_id": aid, "decision": "approve"})
    assert H.po(po_id).status.value == "ISSUED"                       # belum dihapus
    [conv] = H.conversations()
    assert conv.purpose.value == "CANCEL_ORDER" and conv.status.value == "QUEUED"
    assert H.confirmation_status(po_id) == "CANCEL_PENDING"
    assert H.action(aid).status.value == "AWAITING_SUPPLIER"


def test_delete_received_po_is_refused(client, seeded):
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 5)
    item = H.po(po_id).items[0]
    client.post(f"{H.API}/purchase-orders/{po_id}/receipts", json={"items": [{"po_item_id": item.id, "qty_received": 5}]})
    svc, _ = _service({"AutomationParserOutput": F.parsed("delete", po_reference=str(po_id))})
    final = svc.run(f"Hapus PO {po_id}", "thread-auto-6")
    assert not any(b["type"] == "action" for b in final["blocks"])
    assert "cannot be deleted" in final["blocks"][0]["text"]
    assert H.po(po_id) is not None


def test_update_draft_quantity(client, seeded):
    draft = H.draft_po(client, seeded, "RM-TUB-01", "SUP-KRT", 5)
    svc, _ = _service({"AutomationParserOutput": F.parsed("update", po_reference=draft["po_number"],
                                                          items=[F.item("Ban Dalam", 12)])})
    final = svc.run(f"Ubah qty {draft['po_number']} jadi 12", "thread-auto-7")
    aid = _action_id(final)
    assert final["actions"][aid]["kind"] == "update"
    svc.run(None, "thread-auto-7", {"action_id": aid, "decision": "approve"})
    po = H.po(draft["id"])
    assert po.items[0].qty_ordered == 12 and po.total_amount == 12_000 and po.status.value == "DRAFT"


def test_update_issued_po_is_refused(seeded):
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 5)
    svc, _ = _service({"AutomationParserOutput": F.parsed("update", po_reference=str(po_id),
                                                          items=[F.item("Ban Dalam", 8)])})
    final = svc.run("ubah qty", "thread-auto-8")
    assert "Only MANUAL POs in DRAFT or REJECTED" in final["blocks"][0]["text"]


def test_user_can_cancel_a_pending_request(seeded):
    svc, _ = _service({"AutomationParserOutput": [F.parsed(items=[F.item("ban", None)]),
                                                  F.parsed("none", user_cancelled=True)],
                       "AutomationClarifierOutput": F.clarify()})
    svc.run("buat PO ban", "thread-auto-9")
    final = svc.run("batal saja", "thread-auto-9")
    assert "cancelled" in final["blocks"][0]["text"]          # REWRITE fixture -> language "en"
    assert _pos() == []
