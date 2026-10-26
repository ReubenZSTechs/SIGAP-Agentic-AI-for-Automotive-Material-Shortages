"""Agent Hub: persetujuan (revisi PO + proposal misi), percakapan, misi, dokumen, pengaturan.

Memakai pola yang sama dengan test supplier Telegram: fake LLM, transport sandbox, Postgres test.
"""
import base64
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.api.v1.endpoints import hub as hub_api
from app.database import SessionLocal
from app.hub import missions as M
from app.main import app as fastapi_app
from app.models import HubOutbox, MaterialSupplier, POSupplierConfirmation, PurchaseOrder
from configs.tools import po_actions as A
from tests import chat_fakes as F
from tests import po_helpers as H

API = "/api/v1/hub"
WHO = {"approver": "Rina"}
SCRIPT = {"SupplierOutreachOutput": F.OUTREACH, "ManagerEscalationOutput": F.ESCALATION}


def mission_reply(decision="answered", items=None, promised=None, text="Terima kasih, kami teruskan ke tim.",
                  confidence="HIGH", notes=None) -> dict:
    """MissionReplyOutput."""
    return {"decision": decision, "reply_text": text, "items": items or [], "promised_date": promised,
            "guard_flag": "none", "confidence": confidence, "notes": notes}


def quote(sku, price=None, lead=None, qty=None, ready=None) -> dict:
    return {"material_ref": sku, "price_per_unit": price, "lead_time_days": lead, "qty_available": qty, "ready_date": ready}


@pytest.fixture()
def hub(client):
    """(client, svc, fake) dengan service fake disuntikkan ke endpoint /hub."""
    state = {}

    def make(script):
        svc, fake = H.supplier_service({**SCRIPT, **script})
        fastapi_app.dependency_overrides[hub_api.svc] = lambda: svc
        state.update(svc=svc, fake=fake)
        return svc, fake
    yield client, make
    fastapi_app.dependency_overrides.pop(hub_api.svc, None)


def deadline(hours=48) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def link(client, seeded, code):
    r = client.post(f"{API}/suppliers/{seeded['suppliers'][code]}/link-sandbox", json=WHO)
    assert r.status_code == 200, r.text
    return r.json()["chat_id"]


def snap(po_id: int) -> dict:
    with SessionLocal() as db:
        return A.po_snapshot(db.get(PurchaseOrder, po_id))


def price(seeded, sku, code) -> int:
    with SessionLocal() as db:
        return db.scalar(select(MaterialSupplier.unit_price).where(
            MaterialSupplier.material_id == seeded["materials"][sku], MaterialSupplier.supplier_id == seeded["suppliers"][code]))


# ------------------------------------------- status & settings -------------------------------------------
def test_status_and_policies_with_agent_limits(client, seeded):
    st = client.get(f"{API}/status").json()
    assert st["paused"] is False and st["pending"] == 0 and st["telegram"]["mode"] == "sandbox"
    assert "documents" not in st["counts"]
    pol = client.get(f"{API}/policies").json()
    assert {s["key"] for s in pol["scenarios"]} >= {"PRICE_QUOTE", "DELIVERY_CONFIRM", "ESCALATION"}
    assert "DOC_REQUEST" not in {s["key"] for s in pol["scenarios"]}
    assert pol["thresholds"]["delivery_early_days"] == 7 and pol["thresholds"]["delivery_late_days"] == 0
    assert pol["thresholds"]["price_increase_pct"] == 5 and "invoice_tolerance_rp" not in pol["thresholds"]
    assert pol["po_agent"]["max_revision_rounds"] == 2
    pol["scenarios"][1]["outbound"] = "REVIEW"
    pol["thresholds"].update(delivery_early_days=3, delivery_late_days=2, price_increase_pct=7.5)
    saved = client.put(f"{API}/policies", json={**pol, **WHO}).json()
    assert saved["scenarios"][1]["outbound"] == "REVIEW" and saved["thresholds"]["delivery_late_days"] == 2
    bad = {**pol, **WHO, "thresholds": {**pol["thresholds"], "escalate_after_hours": 1}}
    assert client.put(f"{API}/policies", json=bad).status_code == 422
    bad = {**pol, **WHO, "thresholds": {**pol["thresholds"], "price_increase_pct": 150}}
    assert client.put(f"{API}/policies", json=bad).status_code == 422
    bad = {**pol, **WHO, "thresholds": {**pol["thresholds"], "delivery_early_days": 1.5}}
    assert client.put(f"{API}/policies", json=bad).status_code == 422
    assert client.get(f"{API}/templates").status_code == 404                  # template pesan dihapus
    assert client.post(f"{API}/agent/pause", json=WHO).json()["paused"] is True
    assert client.get(f"{API}/status").json()["paused"] is True


def test_suppliers_invite_and_sandbox_link(hub, seeded):
    client, make = hub
    make({})
    sid = seeded["suppliers"]["SUP-KRT"]
    row = next(s for s in client.get(f"{API}/suppliers").json() if s["id"] == sid)
    assert row["telegram"] == "NOT_CONNECTED"
    inv = client.post(f"{API}/suppliers/{sid}/invite", json=WHO).json()
    assert inv["sandbox"] is True and inv["token"]
    assert client.get(f"{API}/suppliers/{sid}").json()["telegram"] == "PENDING"
    link(client, seeded, "SUP-KRT")
    assert client.get(f"{API}/suppliers/{sid}").json()["telegram"] == "CONNECTED"


# ---------------------------------------------- PO revisions ----------------------------------------------
def test_po_revision_listed_and_decided_from_hub(hub, seeded):
    client, make = hub
    reply = F.reply("change_requested", "Kami teruskan ke manajer.", changes=[F.change("RM-RUB-01", "qty", "40")])
    svc, fake = make({"SupplierReplyOutput": reply})
    po_id = H.issue_po(seeded, "RM-RUB-01", "SUP-KRT", 50)
    chat = H.link(svc, seeded, "SUP-KRT")
    H.start(svc, po_id)
    svc.handle_inbound(chat, "Maaf, kami hanya sanggup 40 buah")
    [cr] = H.change_requests()

    items = client.get(f"{API}/approvals").json()
    card = next(i for i in items if i["id"] == f"cr-{cr.id}")
    assert card["type"] == "PO_REVISION" and card["status"] == "PENDING" and not card["stale"]
    assert [o["key"] for o in card["options"]] == ["abort", "approve_change", "resource"]
    assert card["diff"]["rows"][0]["before"] == 50 and card["diff"]["rows"][0]["after"] == 40
    assert client.get(f"{API}/status").json()["pending"] == 1

    fake.script["SupplierReplyOutput"] = [F.reply("confirmed", promised=F.SOON)]
    r = client.post(f"{API}/approvals/cr-{cr.id}/choose", json={**WHO, "choice": "approve_change"})
    assert r.status_code == 200, r.text
    assert H.po(po_id).items[0].qty_ordered == 40
    assert H.change_requests()[0].status.value == "CHANGE_APPROVED"
    assert any("Rina: Setujui perubahan" in m.text for m in H.messages("MANAGER_IN"))
    with SessionLocal() as db:
        assert db.get(PurchaseOrder, po_id).decided_by != "Rina via Hub"     # approve_change tidak membuat PO baru
    again = client.post(f"{API}/approvals/cr-{cr.id}/choose", json={**WHO, "choice": "abort"})
    assert again.status_code == 409
    done = client.get(f"{API}/approvals/cr-{cr.id}").json()
    assert done["status"] == "APPROVED" and done["decided_by"] == "Rina" and done["decision_note"] == "Setujui perubahan"


def test_resource_from_hub_uses_hub_actor(hub, seeded):
    client, make = hub
    reply = F.reply("change_requested", "Kami teruskan.", changes=[F.change("RM-RUB-01", "qty", "40")])
    svc, _ = make({"SupplierReplyOutput": reply})
    po_id = H.issue_po(seeded, "RM-RUB-01", "SUP-KRT", 50)
    chat = H.link(svc, seeded, "SUP-KRT")
    H.start(svc, po_id)
    svc.handle_inbound(chat, "Hanya 40")
    [cr] = H.change_requests()
    r = client.post(f"{API}/approvals/cr-{cr.id}/choose", json={**WHO, "choice": "resource"})
    assert r.status_code == 200, r.text
    new_id = r.json()["new_pos"][0]["id"]
    assert H.po(new_id).decided_by == "Rina via Hub" and H.po(po_id).status.value == "CANCELLED"


# ------------------------------------------------- missions -------------------------------------------------
def test_price_mission_end_to_end_updates_master_price(hub, seeded):
    client, make = hub
    svc, fake = make({"MissionReplyOutput": [mission_reply(items=[quote("RM-PDL-01", 41000, 4)]),
                                             mission_reply("declined", notes="Stok kosong")]})
    mtr, mkm = link(client, seeded, "SUP-MTR"), link(client, seeded, "SUP-MKM")
    body = {**WHO, "scenario": "PRICE_QUOTE", "items": [{"material_id": seeded["materials"]["RM-PDL-01"], "qty": 50}],
            "supplier_ids": [seeded["suppliers"]["SUP-MTR"], seeded["suppliers"]["SUP-MKM"]], "deadline": deadline()}
    r = client.post(f"{API}/missions", json=body)
    assert r.status_code == 201, r.text
    m = r.json()
    assert [t["state"] for t in m["targets"]] == ["SENT", "SENT"] and m["step"] == 3
    opening = H.messages("OUT", mtr)[-1]
    assert "sebanyak 50" in opening.text and opening.agent_output["source"] == "hub_mission"
    assert "Rp" not in opening.text                                          # tidak membocorkan harga kita

    assert svc.handle_inbound(mtr, "Bisa 41rb per buah, 4 hari")["target_state"] == "REPLIED"
    svc.handle_inbound(mkm, "Maaf stok kosong")
    m = client.get(f"{API}/missions/{m['id']}").json()
    assert m["status"] == "DONE" and m["replied"] == 2 and m["approval"]
    thread = client.get(f"{API}/threads/{seeded['suppliers']['SUP-MTR']}").json()
    supplier_msg = next(x for x in thread["messages"] if x["from"] == "SUPPLIER")
    assert any(c["value"] == "Rp41.000" for c in supplier_msg["extracted"])

    card = client.get(f"{API}/approvals/{m['approval']['id']}").json()
    assert card["type"] == "PRICE_UPDATE" and card["diff"]["rows"][0]["before"] == 45000
    assert card["diff"]["rows"][0]["after"] == 41000 and "meta" not in card["diff"]["rows"][0]
    key = card["diff"]["rows"][0]["key"]
    assert client.post(f"{API}/approvals/{card['id']}/approve", json={**WHO, "version": 9}).status_code == 409
    r = client.post(f"{API}/approvals/{card['id']}/approve", json={**WHO, "version": 1, "selected": [key],
                                                                    "edits": {key: 40500}})
    assert r.status_code == 200, r.text
    assert price(seeded, "RM-PDL-01", "SUP-MTR") == 40500
    with SessionLocal() as db:
        lead = db.scalar(select(MaterialSupplier.lead_time_days).where(
            MaterialSupplier.material_id == seeded["materials"]["RM-PDL-01"],
            MaterialSupplier.supplier_id == seeded["suppliers"]["SUP-MTR"]))
    assert lead == 4
    assert client.post(f"{API}/approvals/{card['id']}/approve", json={**WHO, "version": 1}).status_code == 409


def test_stale_price_card_blocks_approval(hub, seeded):
    client, make = hub
    svc, _ = make({"MissionReplyOutput": mission_reply(items=[quote("RM-PDL-01", 41000)])})
    chat = link(client, seeded, "SUP-MTR")
    m = client.post(f"{API}/missions", json={**WHO, "scenario": "PRICE_QUOTE", "deadline": deadline(),
                                             "items": [{"material_id": seeded["materials"]["RM-PDL-01"], "qty": 5}],
                                             "supplier_ids": [seeded["suppliers"]["SUP-MTR"]]}).json()
    svc.handle_inbound(chat, "41rb")
    card_id = client.get(f"{API}/missions/{m['id']}").json()["approval"]["id"]
    client.patch(f"/api/v1/materials/{seeded['materials']['RM-PDL-01']}/suppliers/{seeded['suppliers']['SUP-MTR']}",
                 json={"unit_price": 44000})
    card = client.get(f"{API}/approvals/{card_id}").json()
    assert card["stale"] is True
    assert client.post(f"{API}/approvals/{card_id}/approve", json={**WHO, "version": 1}).status_code == 409
    assert price(seeded, "RM-PDL-01", "SUP-MTR") == 44000


def test_mission_waits_while_po_conversation_is_open(hub, seeded):
    client, make = hub
    svc, fake = make({"SupplierReplyOutput": F.reply("confirmed", promised=F.SOON),
                      "MissionReplyOutput": mission_reply(items=[quote("RM-TUB-01", qty=30)])})
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 20)
    chat = link(client, seeded, "SUP-KRT")
    H.start(svc, po_id)
    m = client.post(f"{API}/missions", json={**WHO, "scenario": "STOCK_CHECK", "deadline": deadline(),
                                             "items": [{"material_id": seeded["materials"]["RM-TUB-01"], "qty": 30}],
                                             "supplier_ids": [seeded["suppliers"]["SUP-KRT"]]}).json()
    assert m["targets"][0]["state"] == "QUEUED"                   # percakapan PO duluan
    svc.handle_inbound(chat, "Siap, PO kami konfirmasi")         # dijawab agent PO, bukan misi
    assert H.confirmation_status(po_id) == "CONFIRMED" and fake.count("MissionReplyOutput") == 0
    M.tick(svc)
    assert client.get(f"{API}/missions/{m['id']}").json()["targets"][0]["state"] == "SENT"
    svc.handle_inbound(chat, "Stok ada 30")
    m = client.get(f"{API}/missions/{m['id']}").json()
    assert m["status"] == "DONE" and m["targets"][0]["result"].startswith("stok 30")


def test_mission_from_po_rules_and_po_untouched(hub, seeded):
    client, make = hub
    svc, _ = make({})
    po_id = H.issue_po(seeded, "RM-RUB-01", "SUP-KRT", 50)
    before = snap(po_id)
    opts = client.get(f"{API}/mission-options/po/{po_id}").json()
    assert opts["items"][0]["qty"] == 50
    assert {s["role"] for s in opts["suppliers"]} == {"PO", "ALT"}           # SUP-RBR sebagai alternatif
    assert next(s for s in opts["scenarios"] if s["key"] == "STOCK_CHECK")["allowed"] is True
    rbr = seeded["suppliers"]["SUP-RBR"]
    base = {**WHO, "deadline": deadline(), "po_id": po_id}
    r = client.post(f"{API}/missions", json={**base, "scenario": "DELIVERY_CONFIRM", "supplier_ids": [rbr]})
    assert r.status_code == 400
    assert client.post(f"{API}/missions", json={**WHO, "deadline": deadline(), "scenario": "DELIVERY_CONFIRM",
                                                "supplier_ids": [rbr]}).status_code == 400
    with A.write_session() as db:
        A.queue_conversation(db, db.get(PurchaseOrder, po_id), A.ConversationPurpose.CONFIRM_ORDER)
    r = client.post(f"{API}/missions", json={**base, "scenario": "DELIVERY_CONFIRM",
                                             "supplier_ids": [seeded["suppliers"]["SUP-KRT"]]})
    assert r.status_code == 409
    r = client.post(f"{API}/missions", json={**base, "scenario": "PRICE_QUOTE",
                                             "supplier_ids": [seeded["suppliers"]["SUP-KRT"], rbr]})
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "PO" and r.json()["items"][0]["qty"] == 50
    ctx = client.get(f"{API}/po/{po_id}/context").json()
    assert ctx["missions"][0]["id"] == r.json()["id"]
    assert snap(po_id) == before


def test_delivery_confirm_creates_delay_card_and_updates_promised_date(hub, seeded):
    client, make = hub
    svc, _ = make({"MissionReplyOutput": mission_reply(promised="2099-01-20")})
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 20)
    with SessionLocal() as db:
        db.get(PurchaseOrder, po_id).items[0].needed_by_date = date(2099, 1, 10)
        db.commit()
    before = snap(po_id)
    chat = link(client, seeded, "SUP-KRT")
    m = client.post(f"{API}/missions", json={**WHO, "scenario": "DELIVERY_CONFIRM", "po_id": po_id, "deadline": deadline(),
                                             "supplier_ids": [seeded["suppliers"]["SUP-KRT"]]}).json()
    assert m["po_number"] and snap(po_id)["po_number"] in H.messages("OUT", chat)[-1].text
    svc.handle_inbound(chat, "Mundur ke 20 Januari")
    card = client.get(f"{API}/approvals/{client.get(f'{API}/missions/{m['id']}').json()['approval']['id']}").json()
    assert card["type"] == "PO_DELAY" and card["diff"]["rows"][0]["after"] == "2099-01-20" and card["risk"] == "HIGH"
    assert client.post(f"{API}/approvals/{card['id']}/approve", json={**WHO, "version": 1}).status_code == 200
    with SessionLocal() as db:
        conf = db.scalar(select(POSupplierConfirmation).where(POSupplierConfirmation.po_id == po_id))
        assert conf.promised_delivery_date == date(2099, 1, 20)
    assert snap(po_id) == before                              # isi PO tidak berubah


def test_review_autonomy_drafts_then_admin_sends(hub, seeded):
    client, make = hub
    make({})
    chat = link(client, seeded, "SUP-MTR")
    m = client.post(f"{API}/missions", json={**WHO, "scenario": "PRICE_QUOTE", "autonomy": "REVIEW", "deadline": deadline(),
                                             "items": [{"material_id": seeded["materials"]["RM-PDL-01"], "qty": 5}],
                                             "supplier_ids": [seeded["suppliers"]["SUP-MTR"]]}).json()
    assert m["targets"][0]["state"] == "QUEUED" and m["targets"][0]["draft"] is True and m["step"] == 2
    assert H.messages("OUT", chat) == []                                    # draf belum dikirim
    thread = client.get(f"{API}/threads/{seeded['suppliers']['SUP-MTR']}").json()
    draft = next(x for x in thread["messages"] if x["status"] == "DRAFT")
    r = client.post(f"{API}/outbox/{draft['outbox_id']}/send", json={**WHO, "text": draft["text"] + " Terima kasih."})
    assert r.status_code == 200, r.text
    assert H.messages("OUT", chat)[-1].text.endswith("Terima kasih.")
    assert client.get(f"{API}/missions/{m['id']}").json()["targets"][0]["state"] == "SENT"
    assert client.post(f"{API}/outbox/{draft['outbox_id']}/send", json=WHO).status_code == 409


def test_remind_escalate_and_close(hub, seeded):
    client, make = hub
    make({})
    link(client, seeded, "SUP-MTR")
    link(client, seeded, "SUP-MKM")
    sids = [seeded["suppliers"]["SUP-MTR"], seeded["suppliers"]["SUP-MKM"]]
    m = client.post(f"{API}/missions", json={**WHO, "scenario": "STOCK_CHECK", "deadline": deadline(),
                                             "items": [{"material_id": seeded["materials"]["RM-PDL-01"], "qty": 5}],
                                             "supplier_ids": sids}).json()
    assert client.post(f"{API}/missions/{m['id']}/remind", json={**WHO, "supplier_ids": [sids[0]]}).json()["count"] == 1
    assert client.post(f"{API}/missions/{m['id']}/escalate", json={**WHO, "supplier_id": sids[1]}).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(HubOutbox).where(HubOutbox.kind == "escalation")).status.value == "DRAFT"
    done = client.post(f"{API}/missions/{m['id']}/close", json=WHO).json()
    assert done["status"] == "DONE" and [t["state"] for t in done["targets"]] == ["NO_REPLY", "ESCALATED"]
    assert client.post(f"{API}/missions/{m['id']}/remind", json=WHO).status_code == 409


def test_pause_stops_mission_sending(hub, seeded):
    client, make = hub
    make({})
    chat = link(client, seeded, "SUP-MTR")
    client.post(f"{API}/agent/pause", json=WHO)
    m = client.post(f"{API}/missions", json={**WHO, "scenario": "STOCK_CHECK", "deadline": deadline(),
                                             "items": [{"material_id": seeded["materials"]["RM-PDL-01"], "qty": 5}],
                                             "supplier_ids": [seeded["suppliers"]["SUP-MTR"]]}).json()
    assert m["targets"][0]["state"] == "QUEUED" and len(H.messages("OUT", chat)) == 0
    client.post(f"{API}/agent/resume", json=WHO)
    client.post(f"{API}/dispatch")
    assert client.get(f"{API}/missions/{m['id']}").json()["targets"][0]["state"] == "SENT"


# ------------------------------------------------ threads ------------------------------------------------
def test_takeover_blocks_agent_and_allows_manual_message(hub, seeded):
    client, make = hub
    svc, fake = make({"SupplierReplyOutput": F.reply("confirmed", promised=F.SOON)})
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 20)
    chat = link(client, seeded, "SUP-KRT")
    H.start(svc, po_id)
    sid = seeded["suppliers"]["SUP-KRT"]
    assert client.post(f"{API}/threads/{sid}/messages", json={**WHO, "text": "Halo"}).status_code == 409
    assert client.post(f"{API}/threads/{sid}/takeover", json=WHO).status_code == 200
    assert svc.handle_inbound(chat, "Siap konfirmasi")["human_mode"] is True
    assert fake.count("SupplierReplyOutput") == 0 and H.confirmation_status(po_id) == "PENDING"
    r = client.post(f"{API}/threads/{sid}/messages", json={**WHO, "text": "Terima kasih Pak, kami cek dulu."})
    assert r.status_code == 201, r.text
    out = H.messages("OUT", chat)[-1]
    assert out.agent_output == {"source": "hub_admin", "author": "Rina"} and out.conversation_id is not None
    thread = client.get(f"{API}/threads/{sid}").json()
    assert thread["mode"] == "HUMAN" and thread["messages"][-1]["from"] == "ADMIN"
    assert any(x["from"] == "SYSTEM" and "mengambil alih" in x["text"] for x in thread["messages"])
    lst = client.get(f"{API}/threads").json()
    assert next(t for t in lst if t["id"] == sid)["unread"] == 0          # dibaca saat thread dibuka
    client.post(f"{API}/threads/{sid}/release", json=WHO)
    svc.handle_inbound(chat, "Siap konfirmasi")
    assert H.confirmation_status(po_id) == "CONFIRMED"


# ----------------------------------------------- documents -----------------------------------------------
def test_sandbox_attachment_is_shown_in_thread(hub, seeded):
    client, make = hub
    make({})
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 20)
    link(client, seeded, "SUP-KRT")
    pdf = b"%PDF-1.4 contoh invoice"
    r = client.post(f"{API}/sandbox/attachment", json={"supplier_id": seeded["suppliers"]["SUP-KRT"],
                                                       "file_name": "INV-9.pdf", "mime": "application/pdf",
                                                       "content_base64": base64.b64encode(pdf).decode()})
    assert r.status_code == 201, r.text
    [doc_id] = r.json()["documents"]
    assert client.get(f"{API}/attachments/{doc_id}/file").content == pdf
    assert client.get(f"{API}/documents/{doc_id}").status_code == 404          # tab Dokumen dihapus
    thread = client.get(f"{API}/threads/{seeded['suppliers']['SUP-KRT']}").json()
    assert any(a["doc_id"] == doc_id for x in thread["messages"] for a in x["attachments"])
    assert "documents" not in thread["context"]
    assert po_id


def test_doc_request_mission_is_no_longer_offered(hub, seeded):
    client, make = hub
    make({})
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 20)
    r = client.post(f"{API}/missions", json={**WHO, "scenario": "DOC_REQUEST", "po_id": po_id, "deadline": deadline(),
                                             "supplier_ids": [seeded["suppliers"]["SUP-KRT"]]})
    assert r.status_code == 422
    assert "DOC_REQUEST" not in {x["key"] for x in client.get(f"{API}/mission-options/po/{po_id}").json()["scenarios"]}


def test_telegram_attachment_update_is_stored(seeded):
    svc, _ = H.supplier_service(SCRIPT)
    chat = H.link(svc, seeded, "SUP-KRT")
    update = {"update_id": 1, "kind": "message", "chat_id": chat, "text": "", "message_id": 7,
              "attachments": [{"file_id": "abc", "name": "foto_7.jpg", "mime": "image/jpeg", "size": 10}]}
    result = svc.handle_update(update)
    assert result["handled"] is True and len(result["documents"]) == 1
    assert H.messages("IN", chat)[-1].text == "[lampiran] foto_7.jpg"


# ------------------------------------------------- manager chat -------------------------------------------------
def test_manager_chat_buttons_and_free_text_from_hub(hub, seeded):
    client, make = hub
    reply = F.reply("change_requested", "Kami teruskan.", changes=[F.change("RM-RUB-01", "qty", "40")])
    svc, _ = make({"SupplierReplyOutput": reply, "ManagerDecisionOutput": F.decision("approve_change")})
    po_id = H.issue_po(seeded, "RM-RUB-01", "SUP-KRT", 50)
    chat = H.link(svc, seeded, "SUP-KRT")
    H.start(svc, po_id)
    svc.handle_inbound(chat, "Hanya 40")
    [cr] = H.change_requests()

    data = client.get(f"{API}/manager/messages").json()
    assert data["pending"] == 1 and data["messages"][-1]["approval_ids"] == [f"cr-{cr.id}"]
    r = client.post(f"{API}/manager/messages", json={**WHO, "text": "setujui saja"})
    assert r.status_code == 200 and r.json()["awaiting_confirmation"] == cr.id
    msgs = client.get(f"{API}/manager/messages").json()["messages"]
    assert msgs[-2]["from"] == "MANAGER" and msgs[-2]["source"] == "hub" and msgs[-2]["text"] == "setujui saja"
    yes, no = msgs[-1]["buttons"]
    assert (yes["state"], no["state"]) == ("active", "active")

    r = client.post(f"{API}/manager/buttons", json={**WHO, "data": no["data"]})
    assert r.status_code == 200 and H.change_requests()[0].status.value == "PENDING_MANAGER"
    assert client.post(f"{API}/manager/buttons", json={**WHO, "data": yes["data"]}).status_code == 409   # sudah dibatalkan
    r = client.post(f"{API}/manager/buttons", json={**WHO, "data": f"cr:{cr.id}:approve_change"})
    assert r.status_code == 200 and H.po(po_id).items[0].qty_ordered == 40
    assert client.get(f"{API}/status").json()["counts"]["manager"] == 0


def test_send_po_to_supplier_from_po_page(hub, seeded):
    client, make = hub
    svc, _ = make({})
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 5)
    H.link(svc, seeded, "SUP-KRT")
    r = client.post(f"{API}/po/{po_id}/supplier-conversation", json={**WHO, "purpose": "CONFIRM_ORDER"})
    assert r.status_code == 201 and r.json()["status"] == "AWAITING_SUPPLIER"
    again = client.post(f"{API}/po/{po_id}/supplier-conversation", json={**WHO, "purpose": "CONFIRM_ORDER"})
    assert again.status_code == 409
    revs = client.get(f"/api/v1/purchase-orders/{po_id}/revisions").json()
    assert [(v["version"], v["status"]) for v in revs] == [(1, "CURRENT")]
    pdf = client.get(f"/api/v1/purchase-orders/{po_id}/revisions/{revs[0]['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    r = client.post(f"{API}/po/{po_id}/supplier-conversation", json={**WHO, "purpose": "CANCEL_ORDER"})
    assert r.status_code == 201 and H.confirmation_status(po_id) == "CANCEL_PENDING"
