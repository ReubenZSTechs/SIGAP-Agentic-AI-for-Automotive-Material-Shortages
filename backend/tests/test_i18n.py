"""English/Indonesian switch on the backend: REST errors, chat texts and cards follow the chosen language."""
import ast
import re
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from app.chatbot.service import ChatService
from app.chatbot.evidence import _LABELS
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


# ------------------------------------------------ coverage: every Indonesian error has an English version
_BACKEND = Path(__file__).resolve().parents[1]
_INDONESIAN = re.compile(r"\b(tidak|belum|sudah|harus|wajib|minimal|maksimal|dulu|sedang|untuk|dengan|ditemukan|"
                         r"dikenal|berlaku|Pilih|Misi|Draf|Pesan|Batas|Ambang|Revisi|Percakapan|Lampiran|Aktivitas|"
                         r"Hanya|Tombol|Otonomi|Skenario|Konfirmasi|Pengiriman|Siklus|Harga|Daftar|Eskalasi|Jam)\b")


def _samples(node) -> list[str]:
    """Example messages for an AppError text: f-string values filled with a few plausible values."""
    def fill(values):
        parts, i = [], 0
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(v.value)
            else:
                parts.append(values[min(i, len(values) - 1)])
                i += 1
        return "".join(parts)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [fill(["X7"]), fill(["7"]), fill(["Material", "7"])]
    return []


def _app_errors():
    for root in ("app", "configs"):
        for path in (_BACKEND / root).rglob("*.py"):
            for n in ast.walk(ast.parse(path.read_text())):
                if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "AppError" and len(n.args) >= 2:
                    samples = _samples(n.args[1])
                    if samples and _INDONESIAN.search(samples[0]):
                        yield f"{path.relative_to(_BACKEND)}:{n.lineno}", samples


def test_every_indonesian_app_error_has_an_english_translation():
    missing = [f"{where}  {samples[0]}" for where, samples in _app_errors()
               if all(translate(m, "en") == m for m in samples)]
    assert not missing, "Add these to app/core/i18n.py (EXACT or PATTERNS):\n" + "\n".join(missing)


def test_chat_table_labels_exist_in_english():
    assert set(_LABELS["id"]) <= set(_LABELS["en"])
