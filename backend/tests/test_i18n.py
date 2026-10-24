"""English/Indonesian switch on the backend: REST errors, chat texts and cards follow the chosen language."""
from langgraph.checkpoint.memory import InMemorySaver

from app.chatbot.service import ChatService
from app.core.i18n import translate
from configs.workflows.chat_graph import build_graph
from tests import chat_fakes as F


def test_translate_exact_patterns_and_fallback():
    assert translate("Supplier tidak ditemukan", "en") == "Supplier not found"
    assert translate("SKU 'RM-X-01' sudah terdaftar", "en") == "SKU 'RM-X-01' is already registered"
    assert translate("Material id=7 tidak ditemukan", "en") == "Material id=7 not found"
    assert translate("Wajib diisi; SKU 'A' sudah terdaftar", "en") == "Required; SKU 'A' is already registered"
    assert translate("teks yang tidak dikenal", "en") == "teks yang tidak dikenal"
    assert translate("Supplier tidak ditemukan", "id") == "Supplier tidak ditemukan"


def test_rest_errors_follow_accept_language(client, seeded):
    r = client.get("/api/v1/suppliers/99999", headers={"Accept-Language": "en"})
    assert r.status_code == 404 and r.json()["detail"] == "Supplier id=99999 not found"
    r = client.get("/api/v1/suppliers/99999")
    assert r.json()["detail"] == "Supplier id=99999 tidak ditemukan"


def _service():
    agents, _, registry = F.fake_agents({"PromptRewriterOutput": F.REWRITE, "RouterOutput": F.ROUTE_MASTER,
                                         "MasterDataParserOutput": F.master("product")})
    return ChatService(build_graph(agents, registry.chatbot, checkpointer=InMemorySaver(),
                                   automation_cfg=registry.automation))


def test_chat_language_overrides_detection_and_translates_master_texts(seeded):
    svc = _service()
    out = svc.run("buat produk baru", "t-i18n-1", language="en")       # REWRITE fake detects "en"; force check below
    assert out["meta"]["language"] == "en"
    form = next(b for b in out["blocks"] if b["type"] == "form")
    assert form["title"] == "New finished product" and form["submitLabel"] == "Review & continue"
    assert out["blocks"][0]["text"].startswith("Please complete the new finished product form below.")
    values = {**form["values"], "sku": "FG-BIKE-01", "name": "", "selling_price": 1}
    again = svc.run(None, "t-i18n-1", {"action_id": form["formId"], "decision": "submit", "values": values}, "en")
    errors = next(b for b in again["blocks"] if b["type"] == "form")["errors"]
    assert errors["sku"] == "SKU 'FG-BIKE-01' is already registered" and errors["name"].startswith("Required")


def test_indonesian_choice_wins_over_detected_english(seeded):
    out = _service().run("create a new product", "t-i18n-2", language="id")
    assert out["meta"]["language"] == "id"
    assert next(b for b in out["blocks"] if b["type"] == "form")["title"] == "Produk final baru"


def test_first_progress_step_uses_the_chosen_language(seeded):
    events = list(_service().stream("buat produk baru", "t-i18n-3", language="en"))
    first = next(e for e in events if e["type"] == "progress")
    assert first["stage"] == "rewrite" and first["label"] == "Understanding the question"
    first_id = next(e for e in _service().stream("buat produk baru", "t-i18n-4", language="id") if e["type"] == "progress")
    assert first_id["label"] == "Memahami pertanyaan"
