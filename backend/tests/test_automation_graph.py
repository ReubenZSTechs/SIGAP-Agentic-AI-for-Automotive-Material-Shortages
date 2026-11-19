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
    assert card["tables"][0]["rows"][0][0] == "Ban Dalam Karet"
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


# ------------------------------ supplier references & stale drafts ------------------------------
def _clarify_from_options(question: str):
    return lambda p: F.clarify(question, [{"label": o["label"], "value": o["value"]}
                                          for a in p["ambiguous"] for o in a["options"]])


def test_supplier_label_with_code_and_name_resolves(seeded):
    svc, _ = _service({"AutomationParserOutput": F.parsed(items=[F.item("Rangka Besi Dudukan Jok", 150)],
                                                          supplier_query="SUP-CPT CV Cipta Logam")})
    card = svc.run("buatlah PO untuk supplier tersebut, 150 biji", "thread-sup-1")
    table = card["actions"][_action_id(card)]["tables"][0]
    assert table["title"].startswith("CV Cipta Logam") and table["rows"][0][0] == "Rangka Besi Dudukan Jok"


def test_unknown_supplier_is_clarified_with_supplier_options(seeded):
    svc, _ = _service({"AutomationParserOutput": F.parsed(items=[F.item("Rangka Besi Dudukan Jok", 150)],
                                                          supplier_query="Toko Antah"),
                       "AutomationClarifierOutput": _clarify_from_options("Supplier mana?")})
    out = svc.run("buat PO 150 rangka besi dari Toko Antah", "thread-sup-2")
    options = next(b for b in out["blocks"] if b["type"] == "options")["options"]
    assert [o["value"] for o in options] == ["SUP-CPT"]


def test_new_request_does_not_inherit_a_failed_supplier(seeded):
    stale = F.parsed(items=[F.item("Rangka Besi Dudukan Jok", 150)], supplier_query="Toko Antah")
    merged_by_mistake = F.parsed(items=[F.item("Ban Luar Karet", 50)], supplier_query="Toko Antah")
    svc, _ = _service({"AutomationParserOutput": [stale, merged_by_mistake],
                       "AutomationClarifierOutput": _clarify_from_options("Supplier mana?")})
    svc.run("buat PO 150 rangka besi dari Toko Antah", "thread-sup-3")
    card = svc.run("Buat PO 50 Ban Luar Karet", "thread-sup-3")
    table = card["actions"][_action_id(card)]["tables"][0]
    assert table["rows"][0][0] == "Ban Luar Karet" and "Toko Antah" not in table["title"]


def test_new_request_flag_resets_clarification_rounds(seeded):
    unknown = F.parsed(items=[F.item("Rangka Besi Dudukan Jok", 150)], supplier_query="Toko Antah")
    svc, _ = _service({"AutomationParserOutput": [unknown, unknown, unknown,
                                                  F.parsed(items=[F.item("Ban Luar Karet")], is_new_request=True)],
                       "AutomationClarifierOutput": _clarify_from_options("Berapa jumlahnya?")})
    for _ in range(3):
        svc.run("dari Toko Antah", "thread-sup-4")                    # 3 putaran klarifikasi (batas)
    out = svc.run("Buat PO Ban Luar Karet", "thread-sup-4")          # permintaan baru tanpa qty
    text = " ".join(b.get("text") or "" for b in out["blocks"])
    assert "Berapa jumlahnya?" in text and "belum lengkap" not in text


def test_rewriter_sees_what_a_proposal_card_contained(seeded):
    svc, fake = _service({"AutomationParserOutput": F.parsed(items=[F.item("Rangka Besi Dudukan Jok", 100)]),
                          "RouterOutput": [F.ROUTE_AUTO, {"intent": "smalltalk", "reason": "thanks"}],
                          "DirectResponderOutput": {"blocks": [{"type": "text", "text": "Sama-sama"}]}})
    svc.run("Buat PO 100 rangka besi", "thread-sup-5")
    svc.run("terima kasih", "thread-sup-5")
    import json
    history = json.loads([c for c in fake.calls if c["agent"] == "PromptRewriterOutput"][-1]["messages"][-1]["content"])
    card_line = next(h["content"] for h in history["conversation_history"] if "[Kartu usulan PO" in h["content"])
    assert "Rangka Besi Dudukan Jok 100 Buah" in card_line and "CV Cipta Logam" in card_line


# ------------------------------ production request: schedule + multi-PO ------------------------------
from datetime import date, timedelta  # noqa: E402

from app.models import Inventory, Schedule  # noqa: E402
from configs.tools import po_actions as A  # noqa: E402


def _produce(qty: int, days: int) -> dict:
    return F.parsed(operation="produce", items=[F.item("Sepeda Gunung", qty)],
                    needed_by_date=(date.today() + timedelta(days=days)).isoformat())


def _po_tables(card: dict) -> dict[str, list]:
    return {t["title"].split(" · ")[0]: t["rows"] for t in card["tables"][1:-1]}   # tabel PO per supplier (tanpa jadwal bayar)


def test_production_request_schedules_and_orders_from_the_fewest_suppliers(seeded):
    calls = []
    svc, _ = _service({"AutomationParserOutput": _produce(100, 10)}, calls)
    out = svc.run("Saya membutuhkan 100 sepeda gunung, materialnya harus siap 10 hari lagi", "thread-prod-1")
    aid = _action_id(out)
    card = out["actions"][aid]
    assert card["kind"] == "produce" and card["title"] == "Production schedule & PO"   # bahasa terdeteksi: en
    check = {r[0]: r for r in card["tables"][0]["rows"]}
    assert check["Besi Tubing / Pipa Baja"][4] == "100" and check["Rangka Besi Dudukan Jok"][4] == "65" \
        and check["Ban Dalam Karet"][4] == "–"
    pos = _po_tables(card)
    assert set(pos) == {"CV Cipta Logam", "PT Karet Nusantara", "CV Makmur Bersama"}                    # BJU lebih murah utk baja, tapi CPT
    assert {r[0] for r in pos["CV Cipta Logam"]} == {"Besi Tubing / Pipa Baja", "Rangka Besi Dudukan Jok"}   # juga memasok rangka jok: 1 PO saja
    assert any("+Rp100.000" in w and "saving 1 PO(s)" in w for w in card["warnings"])
    pay = card["tables"][-1]                                                # jadwal pembayaran sebelum dikirim
    assert pay["title"] == "Payment schedule" and pay["rows"][-1][0] == "Total to pay"
    assert len(pay["rows"]) == 4 and all(r[5] for r in pay["rows"])
    intro = out["blocks"][0]["text"]
    assert "All materials are ready by" in intro and "Total to pay:" in intro
    assert not any(b["type"] == "options" for b in out["blocks"])           # tanggal target bisa dipenuhi

    done = svc.run(None, "thread-prod-1", {"action_id": aid, "decision": "approve"})
    assert done["action_updates"][aid]["status"] == "approved"
    summary, table = done["blocks"]                                         # satu ringkasan + satu tabel PO
    assert summary["type"] == "text" and summary["text"].startswith("Approved.") and "3 POs" in summary["text"]
    assert table["type"] == "table" and len(table["rows"]) == 3 and table["columns"][-1] == "Pay by"
    when = date.today() + timedelta(days=10)
    with SessionLocal() as db:
        [s] = db.query(Schedule).all()
        assert (s.target_qty, s.production_date, s.status.value) == (100, when, "PLANNED")
        steel = db.scalar(select(Inventory).where(Inventory.material_id == seeded["materials"]["RM-STEEL-01"]))
        assert steel.allocated == 150                                        # halaman material: stok terkunci
    issued = [p for p in _pos() if p.status.value == "ISSUED"]
    assert len(issued) == 3 and all(i.needed_by_date == when for p in issued for i in p.items)
    assert all(s.batch_code in p.notes for p in issued) and H.on_order("RM-STEEL-01") == 100
    assert len(H.conversations()) == 3 and calls == ["dispatch"]
    assert H.action(aid).status.value == "AWAITING_SUPPLIER" and H.action(aid).result["schedules"][0]["qty"] == 100


def test_production_for_tomorrow_uses_fastest_suppliers_with_warnings(seeded):
    svc, _ = _service({"AutomationParserOutput": _produce(100, 1)})
    out = svc.run("butuh 100 sepeda gunung besok", "thread-prod-2")
    card = out["actions"][_action_id(out)]
    pos = _po_tables(card)
    assert set(pos) == {"CV Cipta Logam", "CV Rubber Indonesia", "PT Industri Lokal"}                    # RBR satu-satunya yang tepat waktu
    late = [w for w in card["warnings"] if "at the earliest" in w]
    p = H.action(_action_id(out)).proposal
    assert p["feasible"] is False and p["earliest_ready_date"] > p["needed_by_date"]
    option = next(b for b in out["blocks"] if b["type"] == "options")["options"][0]
    assert option["label"] == f"Schedule on {p['earliest_ready_date']}" and p["earliest_ready_date"] in option["value"]
    assert "cannot be met" in out["blocks"][0]["text"]
    assert len(late) == 3 and any(w.startswith("Pedal Sepeda: PT Industri Lokal") for w in late)


def test_production_with_enough_stock_only_schedules(seeded):
    svc, _ = _service({"AutomationParserOutput": _produce(1, 3)})
    out = svc.run("rencanakan produksi 1 sepeda gunung", "thread-prod-3")
    aid = _action_id(out)
    assert len(out["actions"][aid]["tables"]) == 1                          # hanya cek material
    svc.run(None, "thread-prod-3", {"action_id": aid, "decision": "approve"})
    with SessionLocal() as db:
        assert db.query(Schedule).count() == 1
    assert _pos() == [] and H.action(aid).status.value == "EXECUTED"


def test_production_card_is_refused_when_stock_changed_before_approval(seeded):
    svc, _ = _service({"AutomationParserOutput": _produce(100, 10)})
    aid = _action_id(svc.run("butuh 100 sepeda gunung", "thread-prod-4"))
    with SessionLocal() as db:
        db.scalar(select(Inventory).where(Inventory.material_id == seeded["materials"]["RM-RUB-01"])).on_hand = 1000
        db.commit()
    done = svc.run(None, "thread-prod-4", {"action_id": aid, "decision": "approve"})
    assert done["action_updates"][aid]["status"] == "failed" and _pos() == []
    with SessionLocal() as db:
        assert db.query(Schedule).count() == 0


def test_incoming_po_counts_only_when_it_arrives_in_time(seeded):
    when = date.today() + timedelta(days=10)
    po_id = H.issue_po(seeded, "RM-RUB-01", "SUP-KRT", 200)
    draft = _produce(100, 10)

    def rubber_short():
        with SessionLocal() as db:
            res = A.resolve_po_request(db, draft)
        return next(m for m in res["proposal"]["materials"] if m["sku"] == "RM-RUB-01")

    assert rubber_short()["incoming_in_time"] == 0                           # tanpa tanggal: tidak dihitung
    with A.write_session() as db:
        A.confirmation(db, po_id).promised_delivery_date = when + timedelta(days=1)
    assert rubber_short()["incoming_in_time"] == 0                           # terlambat
    with A.write_session() as db:
        A.confirmation(db, po_id).promised_delivery_date = when
    m = rubber_short()
    assert m["incoming_in_time"] == 200 and m["shortfall"] == 0


def test_production_of_product_without_bom_is_an_error(seeded):
    from app.models import Material
    from app.models.enums import ItemCategory
    with SessionLocal() as db:
        db.add(Material(sku="FG-TEST-01", name="Sepeda Lipat", uom="Unit", category=ItemCategory.FINISHED))
        db.commit()
    with SessionLocal() as db:
        res = A.resolve_po_request(db, F.parsed(operation="produce", items=[F.item("Sepeda Lipat", 5)],
                                                needed_by_date=(date.today() + timedelta(days=5)).isoformat()))
    assert res["status"] == "needs_input" and res["errors"][0]["field"] == "bom"


def test_assign_suppliers_covers_with_fewest_suppliers(seeded):
    m = seeded["materials"]
    needs = [{"material_id": m[s], "sku": s, "name": s, "uom": "u", "qty": q}
             for s, q in [("RM-STEEL-01", 10), ("RM-SBR-01", 5), ("RM-PDL-01", 4)]]
    with SessionLocal() as db:
        pick = A.assign_suppliers(db, needs)
        assert {n["sku"]: l["supplier_code"] for l, n, _, _ in pick["assigned"]} == \
            {"RM-STEEL-01": "SUP-CPT", "RM-SBR-01": "SUP-CPT", "RM-PDL-01": "SUP-MKM"}
        assert pick["saved_pos"] == 1 and pick["extra_cost"] == 10 * 1000
        soon = A.assign_suppliers(db, needs[2:], deadline=date.today() + timedelta(days=2))
        assert soon["assigned"][0][0]["supplier_code"] == "SUP-IND" and soon["warnings"] == []
