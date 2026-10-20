"""Supplier revision requests -> manager options (abort / approve change / re-source) -> execution."""
from app.database import SessionLocal
from app.models import PurchaseOrder
from tests import chat_fakes as F
from tests import po_helpers as H

QTY_40 = F.reply("change_requested", "Kami teruskan ke manajer.", changes=[F.change("RM-RUB-01", "qty", "40")],
                 summary="qty 50 -> 40")
SCRIPT = {"SupplierOutreachOutput": F.OUTREACH, "ManagerEscalationOutput": F.ESCALATION}


def _revision(seeded, sku="RM-RUB-01", reply=QTY_40, **script):
    po_id = H.issue_po(seeded, sku, "SUP-KRT", 50)
    svc, fake = H.supplier_service({**SCRIPT, "SupplierReplyOutput": reply, **script})
    chat = H.link(svc, seeded, "SUP-KRT")
    cid = H.start(svc, po_id)
    svc.handle_inbound(chat, "Maaf, kami hanya sanggup 40 buah")
    return po_id, cid, chat, svc, fake


def test_revision_request_offers_all_three_options(seeded):
    po_id, cid, _, _, _ = _revision(seeded)
    [cr] = H.change_requests()
    assert [o["key"] for o in cr.options] == ["abort", "approve_change", "resource"]
    assert cr.proposed_changes[0]["field"] == "qty_ordered" and cr.proposed_changes[0]["new"] == 40
    resource = next(o for o in cr.options if o["key"] == "resource")
    assert resource["purchase_orders"][0]["supplier_code"] == "SUP-RBR"
    assert H.conversation(cid).status.value == "REVISION_REQUESTED"
    assert H.confirmation_status(po_id) == "REVISION_PENDING"
    notice = H.messages("MANAGER_OUT")[-1]
    assert [b["data"] for b in notice.buttons] == [f"cr:{cr.id}:abort", f"cr:{cr.id}:approve_change",
                                                    f"cr:{cr.id}:resource"]
    assert "qty 50 → 40" in notice.text


def test_approve_change_revises_po_and_asks_supplier_to_reconfirm(seeded):
    po_id, cid, chat, svc, fake = _revision(seeded)
    [cr] = H.change_requests()
    fake.script["SupplierReplyOutput"] = [F.reply("confirmed")]
    svc.handle_button(svc.manager_chat_id, f"cr:{cr.id}:approve_change")
    po = H.po(po_id)
    assert po.items[0].qty_ordered == 40 and po.total_amount == 40 * 35_000
    assert H.on_order("RM-RUB-01") == 40
    revision_conv = H.conversations()[-1]
    assert revision_conv.purpose.value == "REVISION_CONFIRM" and revision_conv.status.value == "AWAITING_SUPPLIER"
    assert "40 Buah" in H.messages("OUT", chat)[-1].text
    svc.handle_inbound(chat, "Oke, konfirmasi 40")
    assert H.confirmation_status(po_id) == "CONFIRMED"
    assert H.change_requests()[0].status.value == "CHANGE_APPROVED"


def test_abort_deletes_po_and_notifies_supplier(seeded):
    po_id, _, chat, svc, _ = _revision(seeded)
    [cr] = H.change_requests()
    svc.handle_button(svc.manager_chat_id, f"cr:{cr.id}:abort")
    assert H.po(po_id) is None and H.on_order("RM-RUB-01") == 0
    assert H.change_requests()[0].status.value == "ABORTED"
    assert H.messages("OUT", chat)[-1].text.startswith(F.OUTREACH["message_text"])     # pemberitahuan penarikan


def test_resource_issues_new_po_to_alternative_supplier(seeded):
    po_id, _, _, svc, _ = _revision(seeded)
    rbr_chat = H.link(svc, seeded, "SUP-RBR")
    [cr] = H.change_requests()
    svc.handle_button(svc.manager_chat_id, f"cr:{cr.id}:resource")
    assert H.po(po_id) is None
    with SessionLocal() as db:
        [new] = db.query(PurchaseOrder).all()
        assert new.supplier.code == "SUP-RBR" and new.status.value == "ISSUED" and new.items[0].qty_ordered == 50
        assert new.decided_by == "Manager via Telegram" and new.po_number != cr.po_number
    assert H.on_order("RM-RUB-01") == 50
    new_conv = H.conversations()[-1]
    assert new_conv.supplier_id == seeded["suppliers"]["SUP-RBR"] and new_conv.status.value == "AWAITING_SUPPLIER"
    assert H.messages("OUT", rbr_chat)
    assert H.change_requests()[0].status.value == "RESOURCED"
    assert "dialihkan ke PO baru" in H.messages("MANAGER_OUT")[-1].text


def test_no_resource_option_without_alternative_supplier(seeded):
    reply = F.reply("change_requested", changes=[F.change("RM-TUB-01", "unit_price", "17000")])
    _revision(seeded, sku="RM-TUB-01", reply=reply)
    [cr] = H.change_requests()
    assert [o["key"] for o in cr.options] == ["abort", "approve_change"]


def test_new_chat_after_confirmation_is_triaged_into_a_revision(seeded):
    po_id = H.issue_po(seeded, "RM-RUB-01", "SUP-KRT", 50)
    number = H.po(po_id).po_number
    svc, _ = H.supplier_service({**SCRIPT, "SupplierReplyOutput": [F.reply("confirmed"), QTY_40],
                                 "SupplierInboundTriageOutput": F.triage(number, "revision_request")})
    chat = H.link(svc, seeded, "SUP-KRT")
    H.start(svc, po_id)
    svc.handle_inbound(chat, "siap")
    assert H.confirmation_status(po_id) == "CONFIRMED"
    svc.handle_inbound(chat, f"Maaf, untuk {number} ternyata hanya bisa 40")
    [cr] = H.change_requests()
    assert cr.po_id == po_id and H.confirmation_status(po_id) == "REVISION_PENDING"


def test_free_text_manager_reply_needs_confirmation_button(seeded):
    po_id, _, _, svc, _ = _revision(seeded, ManagerDecisionOutput=F.decision("approve_change"))
    [cr] = H.change_requests()
    svc.handle_inbound(svc.manager_chat_id, "setujui saja")
    assert H.change_requests()[0].status.value == "AWAITING_MANAGER_CONFIRM"
    assert H.po(po_id).items[0].qty_ordered == 50                     # belum dieksekusi
    confirm = H.messages("MANAGER_OUT")[-1].buttons
    assert confirm[0]["data"] == f"crc:{cr.id}:approve_change" and confirm[1]["data"] == f"crx:{cr.id}"
    svc.handle_button(svc.manager_chat_id, confirm[0]["data"])
    assert H.po(po_id).items[0].qty_ordered == 40


def test_po_changed_meanwhile_fails_safely(client, seeded):
    po_id, cid, _, svc, _ = _revision(seeded)
    item = H.po(po_id).items[0]
    client.post(f"{H.API}/purchase-orders/{po_id}/receipts", json={"items": [{"po_item_id": item.id, "qty_received": 10}]})
    [cr] = H.change_requests()
    svc.handle_button(svc.manager_chat_id, f"cr:{cr.id}:abort")
    assert H.po(po_id) is not None and H.change_requests()[0].status.value == "FAILED"
    assert H.conversation(cid).status.value == "ESCALATED"
    assert "Tidak dapat menjalankan" in H.messages("MANAGER_OUT")[-1].text


def test_supplier_buttons_are_ignored(seeded):
    _, _, chat, svc, _ = _revision(seeded)
    [cr] = H.change_requests()
    assert svc.handle_button(chat, f"cr:{cr.id}:abort")["handled"] is False
    assert H.change_requests()[0].status.value == "PENDING_MANAGER"


def test_pick_supplier_policy():
    from configs.tools.po_actions import pick_supplier

    def link(sid, price, lead, moq=1, preferred=False):
        return {"supplier_id": sid, "supplier_code": f"S{sid}", "unit_price": price, "lead_time_days": lead,
                "moq": moq, "is_preferred": preferred}

    cheap, fast, pref = link(1, 100, 5), link(2, 120, 1), link(3, 150, 3, preferred=True)
    assert pick_supplier([cheap, fast], 10)["supplier_id"] == 1                  # termurah
    assert pick_supplier([cheap, fast, pref], 10)["supplier_id"] == 3            # preferred menang
    assert pick_supplier([link(1, 100, 5), link(2, 100, 2)], 10)["supplier_id"] == 2   # harga sama -> tercepat
    assert pick_supplier([link(1, 90, 5, moq=500), fast], 10)["supplier_id"] == 2      # MOQ tak terpenuhi dilewati
    assert pick_supplier([link(1, 90, 5, moq=500)], 10)["supplier_id"] == 1            # satu-satunya -> tetap diusulkan
    assert pick_supplier([cheap, fast], 10, exclude_supplier_id=1)["supplier_id"] == 2  # re-sourcing
    assert pick_supplier([cheap], 10, exclude_supplier_id=1) is None
