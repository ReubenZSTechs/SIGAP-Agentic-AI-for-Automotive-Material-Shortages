"""Supplier Telegram agent in sandbox mode: outreach, confirmation, cancellation, linking, escalation."""
from app.database import SessionLocal
from app.models import PlanningRun, PurchaseOrder
from app.models.enums import ConversationPurpose, PlanningRunStatus
from configs.tools import po_actions as A
from tests import chat_fakes as F
from tests import po_helpers as H

SCRIPT = {"SupplierOutreachOutput": F.OUTREACH, "ManagerEscalationOutput": F.ESCALATION}


def test_opening_message_has_exact_po_summary(seeded):
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 20)
    svc, _ = H.supplier_service(SCRIPT)
    chat = H.link(svc, seeded, "SUP-KRT")
    cid = H.start(svc, po_id)
    assert H.conversation(cid).status.value == "AWAITING_SUPPLIER"
    [out] = H.messages("OUT", chat)[-1:]
    assert out.conversation_id == cid and out.text.startswith(F.OUTREACH["message_text"])
    assert "RM-TUB-01 Ban Dalam Karet — 20 Buah × Rp15.000 = Rp300.000" in out.text


def test_supplier_confirmation_updates_po_confirmation(seeded):
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 20)
    svc, _ = H.supplier_service({**SCRIPT, "SupplierReplyOutput": F.reply("confirmed", promised="2026-10-25", ref="SO-77")})
    chat = H.link(svc, seeded, "SUP-KRT")
    cid = H.start(svc, po_id)
    result = svc.handle_inbound(chat, "Siap, kami kirim tanggal 25")
    assert result["conversation_status"] == "CONFIRMED"
    assert H.confirmation_status(po_id) == "CONFIRMED"
    conv = H.conversation(cid)
    assert conv.status.value == "CONFIRMED" and conv.outcome["promised_delivery_date"] == "2026-10-25"
    assert H.messages("OUT", chat)[-1].text == "Terima kasih."


def test_cancellation_confirmed_deletes_po_and_reverts_stock(client, seeded):
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 20)
    assert H.on_order("RM-TUB-01") == 20
    with SessionLocal() as db:                               # run DRAFT yang harus jadi basi
        from datetime import date
        db.add(PlanningRun(date_from=date(2026, 10, 1), date_to=date(2026, 10, 2), status=PlanningRunStatus.DRAFT))
        db.commit()
    svc, _ = H.supplier_service({**SCRIPT, "SupplierReplyOutput": F.reply("confirmed", "Baik, kami batalkan.")})
    chat = H.link(svc, seeded, "SUP-KRT")
    with A.write_session() as db:
        conv = A.request_po_cancellation(db, {"po": A.po_snapshot(db.get(PurchaseOrder, po_id))}, None)
        cid = conv.id
    svc.dispatch_queued()
    svc.handle_inbound(chat, "Oke, PO dibatalkan")
    assert H.po(po_id) is None and H.on_order("RM-TUB-01") == 0
    conv = H.conversation(cid)
    assert conv.status.value == "CANCEL_CONFIRMED" and conv.po_id is None and conv.po_snapshot["id"] == po_id
    with SessionLocal() as db:
        assert all(r.is_stale for r in db.query(PlanningRun))


def test_cancellation_refused_notifies_manager_and_keeps_po(seeded):
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 20)
    svc, _ = H.supplier_service({**SCRIPT, "SupplierReplyOutput": F.reply("declined", "Maaf, barang sudah diproduksi.")})
    chat = H.link(svc, seeded, "SUP-KRT")
    H.start(svc, po_id, ConversationPurpose.CANCEL_ORDER)
    svc.handle_inbound(chat, "Tidak bisa, sudah produksi")
    assert H.po(po_id).status.value == "ISSUED"
    assert H.confirmation_status(po_id) == "PENDING"
    [notice] = H.messages("MANAGER_OUT")
    assert F.ESCALATION["message_text"] in notice.text and "Tidak bisa, sudah produksi" in notice.text


def test_start_token_links_chat_and_unknown_chats_are_ignored(seeded):
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 5)
    svc, _ = H.supplier_service(SCRIPT)
    cid = H.start(svc, po_id)
    assert H.conversation(cid).status.value == "QUEUED"        # supplier belum tertaut
    assert "belum terhubung" in H.messages("MANAGER_OUT")[0].text
    assert svc.handle_inbound(555, "halo")["reason"] == "unknown_chat"
    with SessionLocal() as db:
        from app.supplier_chat.service import ensure_link
        token = ensure_link(db, seeded["suppliers"]["SUP-KRT"]).link_token
        db.commit()
    assert svc.handle_inbound(555, "/start wrong-token")["linked"] is False
    assert svc.handle_inbound(555, f"/start {token}")["linked"] is True
    assert H.conversation(cid).status.value == "AWAITING_SUPPLIER"   # antrean langsung dikirim


def test_unclear_replies_escalate_after_max_turns(seeded):
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 5)
    svc, _ = H.supplier_service({**SCRIPT, "SupplierReplyOutput": F.reply("unclear", "Mohon konfirmasi ya/tidak.")},
                                max_turns=2)
    chat = H.link(svc, seeded, "SUP-KRT")
    cid = H.start(svc, po_id)
    svc.handle_inbound(chat, "hmm")
    assert H.conversation(cid).status.value == "AWAITING_SUPPLIER"
    svc.handle_inbound(chat, "nanti ya")
    assert H.conversation(cid).status.value == "ESCALATED"
    assert len(H.messages("MANAGER_OUT")) == 1


def test_one_active_conversation_per_supplier(seeded):
    first, second = (H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 5), H.issue_po(seeded, "RM-RUB-01", "SUP-KRT", 5))
    svc, _ = H.supplier_service({**SCRIPT, "SupplierReplyOutput": F.reply("confirmed")})
    chat = H.link(svc, seeded, "SUP-KRT")
    c1, c2 = H.start(svc, first), H.start(svc, second)
    assert (H.conversation(c1).status.value, H.conversation(c2).status.value) == ("AWAITING_SUPPLIER", "QUEUED")
    svc.handle_inbound(chat, "ok siap")
    assert (H.conversation(c1).status.value, H.conversation(c2).status.value) == ("CONFIRMED", "AWAITING_SUPPLIER")


def test_sandbox_api_round_trip(client, seeded):
    """The Streamlit harness path: link, start, reply as supplier via HTTP."""
    import app.api.v1.endpoints.supplier_chat as ep
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 5)
    svc, _ = H.supplier_service({**SCRIPT, "SupplierReplyOutput": F.reply("confirmed")})
    client.app.dependency_overrides[ep.service] = lambda: svc
    try:
        sid = seeded["suppliers"]["SUP-KRT"]
        assert client.post(f"{H.API}/supplier-chat/links/{sid}/sandbox").status_code == 200
        r = client.post(f"{H.API}/supplier-chat/conversations", json={"po_id": po_id, "purpose": "CONFIRM_ORDER"})
        assert r.status_code == 201 and r.json()["status"] == "AWAITING_SUPPLIER"
        r = client.post(f"{H.API}/supplier-chat/sandbox/inbound", json={"supplier_id": sid, "text": "siap"})
        assert r.status_code == 200 and [m["direction"] for m in r.json()["messages"]] == ["IN", "OUT"]
        detail = client.get(f"{H.API}/supplier-chat/conversations/{r.json()['messages'][0]['conversation_id']}").json()
        assert detail["status"] == "CONFIRMED" and detail["confirmation"]["status"] == "CONFIRMED"
        assert any(l["linked"] for l in client.get(f"{H.API}/supplier-chat/links").json())
    finally:
        client.app.dependency_overrides.pop(ep.service, None)


def test_telegram_mode_ignores_sandbox_link_and_resends_after_real_link(seeded):
    """Sandbox chat ids are not real Telegram chats; linking via /start re-sends the failed opening."""
    from app.supplier_chat.transport import SandboxTransport

    class FakeTelegram(SandboxTransport):
        name = "telegram"
        def send(self, chat_id, text, buttons=None):
            if chat_id >= 10_000_000 and chat_id < 10_100_000:
                raise RuntimeError("chat not found")
            return 1

    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 5)
    svc, _ = H.supplier_service(SCRIPT)
    svc.transport = FakeTelegram()
    svc.manager_chat_id = 42
    H.link(svc, seeded, "SUP-KRT")                                 # tautan sandbox lama
    cid = H.start(svc, po_id)
    assert H.conversation(cid).status.value == "QUEUED"            # tidak dikirim ke chat palsu
    with SessionLocal() as db:
        from app.supplier_chat.service import ensure_link
        token = ensure_link(db, seeded["suppliers"]["SUP-KRT"]).link_token
        db.commit()
    assert svc.handle_inbound(42, f"/start {token}")["reason"] == "manager_chat"   # akun manajer ditolak
    assert svc.handle_inbound(777, f"/start {token}")["linked"] is True
    assert H.conversation(cid).status.value == "AWAITING_SUPPLIER"
    assert [m.error for m in H.messages("OUT", 777)][-1] is None
