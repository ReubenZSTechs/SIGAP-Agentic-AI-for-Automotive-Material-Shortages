"""Supplier revision requests -> manager options (abort / approve change / re-source) -> execution."""
import pytest

from app.database import SessionLocal
from app.models import PurchaseOrder
from tests import chat_fakes as F
from tests import po_helpers as H

QTY_40 = F.reply("change_requested", "Kami teruskan ke manajer.", changes=[F.change("RM-RUB-01", "qty", "40")],
                 summary="qty 50 -> 40")
SCRIPT = {"SupplierOutreachOutput": F.OUTREACH, "ManagerEscalationOutput": F.ESCALATION}


def _revision(seeded, sku="RM-RUB-01", reply=QTY_40, transport=None, **script):
    po_id = H.issue_po(seeded, sku, "SUP-KRT", 50)
    svc, fake = H.supplier_service({**SCRIPT, "SupplierReplyOutput": reply, **script}, transport=transport)
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
    ask = H.messages("OUT", chat)[-1].text
    assert "RM-RUB-01 Ban Luar Karet: qty 50 → 40" in ask and "Total: Rp1.750.000 → Rp1.400.000" in ask
    assert "Termin: Net" not in ask                                   # PO lengkap tidak dikirim ulang
    v1, v2 = H.revisions(po_id)
    assert (v1.status.value, v2.status.value) == ("SUPERSEDED", "CURRENT") and v2.changes[0]["new"] == 40
    svc.handle_inbound(chat, "Oke, konfirmasi 40, tidak ada perubahan lagi")
    assert H.confirmation_status(po_id) == "CONFIRMED"
    assert H.change_requests()[0].status.value == "CHANGE_APPROVED"
    final = H.revisions(po_id)[-1]
    assert final.version == 2 and final.status.value == "FINAL" and final.snapshot["total_amount"] == 40 * 35_000
    pdf = H.messages("OUT", chat)[-1]
    assert pdf.agent_output["source"] == "po_pdf" and pdf.agent_output["revision_id"] == final.id
    assert final.pdf_message_id == pdf.id


def test_first_confirmation_saves_v1_as_final_and_sends_pdf(seeded):
    transport = H.RecordingTransport()
    po_id = H.issue_po(seeded, "RM-RUB-01", "SUP-KRT", 50)
    svc, _ = H.supplier_service({**SCRIPT, "SupplierReplyOutput": F.reply("confirmed")}, transport=transport)
    chat = H.link(svc, seeded, "SUP-KRT")
    H.start(svc, po_id)
    [v1] = H.revisions(po_id)
    assert v1.status.value == "CURRENT"
    svc.handle_inbound(chat, "siap, kami kirim minggu depan")
    [v1] = H.revisions(po_id)
    assert v1.status.value == "FINAL"
    [(to, name, content, caption)] = transport.documents
    assert to == chat and name == f"{v1.po_number}-v1.pdf" and content.startswith(b"%PDF") and "final" in caption


def test_reminder_does_not_resend_the_po(seeded):
    po_id = H.issue_po(seeded, "RM-RUB-01", "SUP-KRT", 50)
    svc, _ = H.supplier_service(SCRIPT, reminder_after_hours=0)
    chat = H.link(svc, seeded, "SUP-KRT")
    H.start(svc, po_id)
    assert svc.tick_timeouts()["reminded"] == 1
    reminder = H.messages("OUT", chat)[-1].text
    assert reminder.startswith("Pengingat") and "Termin: Net" not in reminder


def test_hub_decision_removes_telegram_buttons_and_logs_once(seeded):
    from app.hub import approvals, manager
    transport = H.RecordingTransport()
    po_id, _, _, svc, fake = _revision(seeded, transport=transport)
    [cr] = H.change_requests()
    options = H.messages("MANAGER_OUT")[-1]
    with SessionLocal() as db:
        assert [b["state"] for b in manager.manager_thread(db)["messages"][-1]["buttons"]] == ["active"] * 3
    fake.script["SupplierReplyOutput"] = [F.reply("confirmed")]
    approvals.choose_change_request(svc, cr.id, "approve_change", "Rina")
    assert (svc.manager_chat_id, options.telegram_message_id, None) in transport.edited
    assert any("Diputuskan via Hub oleh Rina" in text for _, text, _ in transport.sent)
    with SessionLocal() as db:
        thread = manager.manager_thread(db)["messages"]
    states = next(m for m in thread if m["id"] == options.id)["buttons"]
    assert [b["state"] for b in states] == ["closed", "chosen", "closed"]
    hub_reply = [m for m in thread if m["from"] == "MANAGER"]
    assert hub_reply[-1]["source"] == "hub" and hub_reply[-1]["author"] == "Rina"
    assert not any("Diputuskan via Hub" in m["text"] for m in thread)     # dicerminkan ke Telegram, tidak dicatat dua kali


def test_telegram_decision_is_recorded_for_the_hub(seeded):
    from app.hub import approvals
    transport = H.RecordingTransport()
    _, _, _, svc, _ = _revision(seeded, transport=transport)
    [cr] = H.change_requests()
    svc.handle_button(svc.manager_chat_id, f"cr:{cr.id}:abort")
    assert transport.edited and transport.edited[-1][2] is None
    with SessionLocal() as db:
        card = approvals.get_approval(db, f"cr-{cr.id}")
    assert card["status"] == "APPROVED" and card["decided_by"] == "Manager via Telegram"


def test_parse_rupiah_formats():
    from configs.tools.po_actions import parse_rupiah
    cases = {"12500": 12_500, "12.500": 12_500, "Rp 12.500": 12_500, "Rp12.500,00": 12_500, "12500.00": 12_500,
             "12,500": 12_500, "1.250.000": 1_250_000, "17000": 17_000}
    assert {raw: parse_rupiah(raw) for raw in cases} == cases
    for bad in ("", "harga naik", "Rp"):
        with pytest.raises(ValueError):
            parse_rupiah(bad)


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


def test_stale_yes_button_after_cancel_does_nothing(seeded):
    po_id, _, _, svc, _ = _revision(seeded, ManagerDecisionOutput=F.decision("approve_change"))
    svc.handle_inbound(svc.manager_chat_id, "setujui saja")
    yes, no = H.messages("MANAGER_OUT")[-1].buttons
    svc.handle_button(svc.manager_chat_id, no["data"])
    svc.handle_button(svc.manager_chat_id, yes["data"])
    assert H.po(po_id).items[0].qty_ordered == 50 and H.change_requests()[0].status.value == "PENDING_MANAGER"
    assert "sudah tidak berlaku" in H.messages("MANAGER_OUT")[-1].text


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
