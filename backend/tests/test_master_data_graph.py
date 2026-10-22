"""New product / material / supplier from the Dashboard chat: form -> submit -> confirm -> one transaction."""
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.chatbot.service import ChatService
from app.database import SessionLocal
from app.models import AutomationAction, BOMItem, Inventory, Material, MaterialSupplier, StockMovement, Supplier
from configs.workflows.chat_graph import build_graph
from tests import chat_fakes as F


def _service(script: dict):
    base = {"PromptRewriterOutput": F.REWRITE, "RouterOutput": F.ROUTE_MASTER}
    agents, fake, registry = F.fake_agents({**base, **script})
    graph = build_graph(agents, registry.chatbot, checkpointer=InMemorySaver(), automation_cfg=registry.automation)
    return ChatService(graph), fake


def _form(final: dict) -> dict:
    return next(b for b in final["blocks"] if b["type"] == "form")


def _action_id(final: dict) -> str:
    return next(b["actionId"] for b in final["blocks"] if b["type"] == "action")


def _submit(svc, thread, form, values):
    return svc.run(None, thread, {"action_id": form["formId"], "decision": "submit", "values": values})


def _approve(svc, thread, final):
    return svc.run(None, thread, {"action_id": _action_id(final), "decision": "approve"})


def _material(sku: str) -> Material | None:
    with SessionLocal() as db:
        return db.scalar(select(Material).where(Material.sku == sku))


def _count(model) -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(model)).all())


def _new_material(sku, name, uom="Buah", initial_stock=0, **kw) -> dict:
    return {"sku": sku, "name": name, "uom": uom, "initial_stock": initial_stock,
            "supplier_id": kw.get("supplier_id"), "unit_price": kw.get("unit_price"),
            "lead_time_days": kw.get("lead_time_days")}


def test_product_with_existing_and_new_material_is_created_in_one_go(seeded):
    svc, _ = _service({"MasterDataParserOutput": F.master(
        "product", name="Sepeda Lipat", selling_price=3_000_000,
        items=[F.master_item("Pedal Sepeda", 2), F.master_item("Rangka Titanium Lipat", 1)])})
    first = svc.run("Buat produk baru Sepeda Lipat harga 3 juta, pakai 2 Pedal Sepeda dan 1 Rangka Titanium Lipat",
                    "t-prod-1")
    assert first["meta"]["intent"] == "master_data"
    form = _form(first)
    values = form["values"]
    assert values["name"] == "Sepeda Lipat" and values["selling_price"] == 3_000_000 and values["uom"] == "Unit"
    pedal, frame = values["components"]
    assert pedal["material_id"] == seeded["materials"]["RM-PDL-01"] and pedal["qty"] == 2
    assert frame["material_id"] is None and frame["new_material"]["name"] == "Rangka Titanium Lipat"
    assert {o["category"] for o in form["options"]["materials"]} == {"PURCHASED", "SUB_PART"}
    assert svc.pending_action("t-prod-1") == form["formId"]

    values["sku"] = "FG-FOLD-01"
    frame["new_material"].update(sku="RM-TIT-01", initial_stock=5, supplier_id=seeded["CIPTA"],
                                 unit_price=150000, lead_time_days=6)
    card_turn = _submit(svc, "t-prod-1", form, values)
    aid = _action_id(card_turn)
    card = card_turn["actions"][aid]
    assert card["kind"] == "new_product" and card["status"] == "pending"
    assert _material("FG-FOLD-01") is None                       # belum ada yang disimpan sebelum konfirmasi

    done = _approve(svc, "t-prod-1", card_turn)
    assert done["action_updates"][aid]["status"] == "approved"
    assert any(b["type"] == "link" and b["to"] == "/products" for b in done["blocks"])
    product, frame_m = _material("FG-FOLD-01"), _material("RM-TIT-01")
    assert product.category.value == "FINISHED" and product.selling_price == 3_000_000
    assert frame_m.category.value == "PURCHASED"
    with SessionLocal() as db:
        bom = {b.child_id: b.qty_per_parent for b in db.scalars(select(BOMItem).where(BOMItem.parent_id == product.id))}
        inv = db.scalar(select(Inventory).where(Inventory.material_id == frame_m.id))
        link = db.scalar(select(MaterialSupplier).where(MaterialSupplier.material_id == frame_m.id))
        moves = db.scalars(select(StockMovement).where(StockMovement.material_id == frame_m.id)).all()
    assert bom == {seeded["materials"]["RM-PDL-01"]: 2, frame_m.id: 1}
    assert inv.on_hand == 5 and len(moves) == 1
    assert link.supplier_id == seeded["CIPTA"] and link.unit_price == 150000 and link.lead_time_days == 6
    with SessionLocal() as db:
        assert db.get(AutomationAction, aid).status.value == "EXECUTED"
    assert svc.pending_action("t-prod-1") is None


def test_invalid_form_is_shown_again_with_errors_and_values(seeded):
    svc, _ = _service({"MasterDataParserOutput": F.master("product")})
    form = _form(svc.run("Saya ingin membuat produk baru", "t-prod-2"))
    values = {**form["values"], "sku": "FG-BIKE-01", "name": "", "selling_price": -5,
              "components": [{"material_id": seeded["BIKE"], "new_material": None, "qty": 1},
                             {"material_id": None, "new_material": _new_material("RM-X-01", "X"), "qty": 0},
                             {"material_id": None, "new_material": _new_material("RM-X-01", "Y"), "qty": 1}]}
    again = _submit(svc, "t-prod-2", form, values)
    errors = _form(again)["errors"]
    assert errors["sku"] == "SKU 'FG-BIKE-01' sudah terdaftar"
    assert errors["name"].startswith("Wajib diisi") and errors["selling_price"] == "Minimal 0"
    assert "Produk Final tidak dapat menjadi komponen BOM" in errors["components.0.material_id"]
    assert errors["components.1.qty"] == "Harus lebih dari 0"
    assert "lebih dari sekali" in errors["components.2.new_material.sku"]
    assert _form(again)["values"]["sku"] == "FG-BIKE-01"
    assert _form(again)["emptyValues"] == {"sku": "", "name": "", "uom": "Unit", "selling_price": None,
                                           "specification": "", "components": []}
    assert _count(AutomationAction) == 0


def test_product_without_bom_is_allowed_with_a_warning(seeded):
    svc, _ = _service({"MasterDataParserOutput": F.master("product")})
    form = _form(svc.run("produk baru", "t-prod-3"))
    card_turn = _submit(svc, "t-prod-3", form, {**form["values"], "sku": "FG-NEW-01", "name": "Skuter",
                                                "selling_price": 900000})
    card = card_turn["actions"][_action_id(card_turn)]
    assert any("belum punya BOM" in w for w in card["warnings"])
    _approve(svc, "t-prod-3", card_turn)
    assert _material("FG-NEW-01").category.value == "FINISHED"


def test_cancel_and_reject_change_nothing(seeded):
    svc, _ = _service({"MasterDataParserOutput": F.master("material")})
    form = _form(svc.run("tambah material baru", "t-mat-1"))
    out = svc.run(None, "t-mat-1", {"action_id": form["formId"], "decision": "reject"})
    assert "dibatalkan" in out["blocks"][0]["text"] and svc.pending_action("t-mat-1") is None

    form = _form(svc.run("tambah material baru", "t-mat-1"))
    card_turn = _submit(svc, "t-mat-1", form, {**form["values"], "sku": "RM-NEW-01", "name": "Baut Baru"})
    out = svc.run(None, "t-mat-1", {"action_id": _action_id(card_turn), "decision": "reject"})
    assert "tidak disimpan" in out["blocks"][0]["text"]
    assert _material("RM-NEW-01") is None


def test_typing_while_the_form_is_open_continues_the_draft(seeded):
    svc, _ = _service({"MasterDataParserOutput": [
        F.master("product", name="Sepeda Anak"),
        F.master("product", selling_price=1_500_000, items=[F.master_item("Rantai Sepeda", 1)])]})
    first = _form(svc.run("buat produk Sepeda Anak", "t-prod-4"))
    second = _form(svc.run("harganya 1,5 juta dan pakai 1 rantai sepeda", "t-prod-4"))
    assert second["formId"] != first["formId"]
    v = second["values"]
    assert v["name"] == "Sepeda Anak" and v["selling_price"] == 1_500_000
    assert v["components"][0]["material_id"] == seeded["materials"]["RM-CHN-01"]
    stale = svc.run(None, "t-prod-4", {"action_id": first["formId"], "decision": "submit", "values": v})
    assert stale["type"] == "error"


def test_material_with_existing_and_new_supplier(seeded):
    svc, _ = _service({"MasterDataParserOutput": F.master(
        "material", name="Lampu Sepeda", items=[F.master_item("SUP-ASN", unit_price=25000, lead_time_days=3),
                                                F.master_item("PT Cahaya Terang")])})
    form = _form(svc.run("tambah material Lampu Sepeda dari SUP-ASN 25rb 3 hari dan PT Cahaya Terang", "t-mat-2"))
    asn, new = form["values"]["suppliers"]
    assert asn["supplier_id"] == seeded["suppliers"]["SUP-ASN"] and asn["unit_price"] == 25000
    assert new["new_supplier"]["name"] == "PT Cahaya Terang"
    new["new_supplier"]["code"] = "SUP-CHY"
    new.update(unit_price=24000, lead_time_days=5, is_preferred=True)
    values = {**form["values"], "sku": "RM-LMP-01", "initial_stock": 10, "safety_stock": 4}
    _approve(svc, "t-mat-2", _submit(svc, "t-mat-2", form, values))
    lamp = _material("RM-LMP-01")
    with SessionLocal() as db:
        sup = db.scalar(select(Supplier).where(Supplier.code == "SUP-CHY"))
        links = {l.supplier_id: l for l in db.scalars(select(MaterialSupplier).where(MaterialSupplier.material_id == lamp.id))}
        inv = db.scalar(select(Inventory).where(Inventory.material_id == lamp.id))
    assert sup.name == "PT Cahaya Terang" and links[sup.id].is_preferred and links[sup.id].unit_price == 24000
    assert links[seeded["suppliers"]["SUP-ASN"]].lead_time_days == 3
    assert (inv.on_hand, inv.safety_stock) == (10, 4)


def test_supplier_with_existing_and_new_material(seeded):
    svc, _ = _service({"MasterDataParserOutput": F.master(
        "supplier", code="SUP-NEW", name="CV Baru Jaya", payment_term_days=30,
        items=[F.master_item("Ban Luar Karet", unit_price=34000, lead_time_days=2), F.master_item("Bel Sepeda")])})
    form = _form(svc.run("daftarkan supplier CV Baru Jaya", "t-sup-1"))
    rub, bell = form["values"]["materials"]
    assert rub["material_id"] == seeded["materials"]["RM-RUB-01"]
    bell["new_material"]["sku"] = "RM-BEL-01"
    bell.update(unit_price=8000, lead_time_days=4)
    card_turn = _submit(svc, "t-sup-1", form, form["values"])
    card = card_turn["actions"][_action_id(card_turn)]
    assert card["kind"] == "new_supplier"
    _approve(svc, "t-sup-1", card_turn)
    with SessionLocal() as db:
        sup = db.scalar(select(Supplier).where(Supplier.code == "SUP-NEW"))
        linked = {l.material.sku for l in sup.material_links}
        inv = db.scalar(select(Inventory).join(Material).where(Material.sku == "RM-BEL-01"))
    assert sup.payment_term_days == 30 and linked == {"RM-RUB-01", "RM-BEL-01"}
    assert inv is not None and inv.on_hand == 0


def test_supplier_link_to_a_finished_product_is_refused(seeded):
    svc, _ = _service({"MasterDataParserOutput": F.master("supplier")})
    form = _form(svc.run("supplier baru", "t-sup-2"))
    values = {**form["values"], "code": "SUP-ZZ", "name": "Z",
              "materials": [{"material_id": seeded["BIKE"], "new_material": None, "unit_price": 1,
                             "lead_time_days": 1, "moq": 1, "is_preferred": False}]}
    errors = _form(_submit(svc, "t-sup-2", form, values))["errors"]
    assert errors["materials.0.material_id"] == "FG-BIKE-01 bukan material beli"


def test_sku_taken_after_the_card_was_shown_fails_and_rolls_back(seeded):
    svc, _ = _service({"MasterDataParserOutput": F.master("supplier")})
    form = _form(svc.run("supplier baru", "t-sup-3"))
    values = {**form["values"], "code": "SUP-RACE", "name": "Race",
              "materials": [{"material_id": None, "new_material": _new_material("RM-RACE-01", "Race Part"),
                             "unit_price": 10, "lead_time_days": 1, "moq": 1, "is_preferred": False}]}
    card_turn = _submit(svc, "t-sup-3", form, values)
    with SessionLocal() as db:                                   # orang lain mendaftarkan SKU yang sama
        db.add(Material(sku="RM-RACE-01", name="Other", uom="Buah"))
        db.commit()
    out = _approve(svc, "t-sup-3", card_turn)
    assert out["action_updates"][_action_id(card_turn)]["status"] == "failed"
    assert "sudah terdaftar" in out["blocks"][0]["text"]
    with SessionLocal() as db:
        assert db.scalar(select(Supplier).where(Supplier.code == "SUP-RACE")) is None


def test_unclear_entity_offers_the_three_choices(seeded):
    svc, _ = _service({"MasterDataParserOutput": F.master("none")})
    out = svc.run("saya mau tambah data baru", "t-none")
    options = next(b for b in out["blocks"] if b["type"] == "options")["options"]
    assert [o["label"] for o in options] == ["Produk final baru", "Material beli baru", "Supplier baru"]


def test_resume_values_are_only_accepted_on_submit(client):
    body = {"thread_id": "thread-abc-123", "resume": {"action_id": "a" * 32, "decision": "approve", "values": {}}}
    assert client.post("/api/v1/chat", json=body).status_code == 422


def test_new_material_in_a_product_can_get_a_new_supplier_and_safety_stock(seeded):
    svc, _ = _service({"MasterDataParserOutput": F.master("product", name="DGX Station", selling_price=500_000_000)})
    form = _form(svc.run("buat produk DGX Station", "t-prod-5"))
    new_mat = {**_new_material("RM-CSG-01", "Casing DGX", initial_stock=2), "safety_stock": 1,
               "new_supplier": {"code": "SUP-NVD", "name": "PT Nvidia Indonesia", "contact": "", "payment_term_days": 30},
               "unit_price": 2_000_000, "lead_time_days": 7}
    values = {**form["values"], "sku": "FG-DGX-01",
              "components": [{"material_id": None, "new_material": new_mat, "qty": 1}]}
    card_turn = _submit(svc, "t-prod-5", form, values)
    card = card_turn["actions"][_action_id(card_turn)]
    assert not any("tanpa supplier" in w for w in card["warnings"])
    _approve(svc, "t-prod-5", card_turn)
    casing = _material("RM-CSG-01")
    with SessionLocal() as db:
        sup = db.scalar(select(Supplier).where(Supplier.code == "SUP-NVD"))
        link = db.scalar(select(MaterialSupplier).where(MaterialSupplier.material_id == casing.id))
        inv = db.scalar(select(Inventory).where(Inventory.material_id == casing.id))
    assert sup.payment_term_days == 30 and link.supplier_id == sup.id and link.lead_time_days == 7
    assert (inv.on_hand, inv.safety_stock) == (2, 1)


def test_new_supplier_of_a_new_material_needs_code_price_and_lead_time(seeded):
    svc, _ = _service({"MasterDataParserOutput": F.master("product")})
    form = _form(svc.run("produk baru", "t-prod-6"))
    new_mat = {**_new_material("RM-ZZ-01", "Z"), "new_supplier": {"code": "", "name": "X", "contact": "",
                                                                    "payment_term_days": 0}}
    values = {**form["values"], "sku": "FG-ZZ-01", "name": "Z", "selling_price": 1,
              "components": [{"material_id": None, "new_material": new_mat, "qty": 1}]}
    errors = _form(_submit(svc, "t-prod-6", form, values))["errors"]
    assert errors["components.0.new_material.new_supplier.code"].startswith("Wajib diisi")
    assert errors["components.0.new_material.unit_price"] == "Wajib diisi"
    assert errors["components.0.new_material.lead_time_days"] == "Wajib diisi"
