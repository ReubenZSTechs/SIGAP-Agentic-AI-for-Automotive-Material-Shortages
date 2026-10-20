"""Progress events streamed to the UI through LangGraph's custom stream mode."""
from contextlib import contextmanager
from contextvars import ContextVar

from langgraph.config import get_stream_writer

LABELS = {
    "rewrite": {"id": "Memahami pertanyaan", "en": "Understanding the question"},
    "route": {"id": "Menentukan jenis permintaan", "en": "Classifying the request"},
    "plan": {"id": "Merencanakan pengambilan data", "en": "Planning data retrieval"},
    "tool": {"id": "Mengambil data", "en": "Fetching data"},
    "sql_generate": {"id": "Menyusun query database", "en": "Writing a database query"},
    "sql_execute": {"id": "Menjalankan query (read-only)", "en": "Running the query (read-only)"},
    "sql_fix": {"id": "Memperbaiki query", "en": "Fixing the query"},
    "synthesize": {"id": "Menyusun jawaban", "en": "Drafting the answer"},
    "evaluate": {"id": "Memverifikasi jawaban", "en": "Verifying the answer"},
    "revise": {"id": "Memperbaiki jawaban", "en": "Revising the answer"},
    "respond": {"id": "Menyusun balasan", "en": "Writing a reply"},
    "auto_parse": {"id": "Memahami permintaan PO", "en": "Understanding the PO request"},
    "auto_resolve": {"id": "Mencocokkan dengan database", "en": "Matching against the database"},
    "auto_clarify": {"id": "Menyiapkan pertanyaan klarifikasi", "en": "Preparing a clarification"},
    "auto_propose": {"id": "Menyiapkan usulan untuk dikonfirmasi", "en": "Preparing the proposal"},
    "auto_execute": {"id": "Menjalankan perubahan PO", "en": "Applying the PO change"},
    "supplier_contact": {"id": "Menghubungi supplier via Telegram", "en": "Contacting the supplier on Telegram"},
}

_parent_writer: ContextVar = ContextVar("chat_parent_writer", default=None)


def current_writer():
    """Writer of the outer graph run if one was forwarded, else this run's writer (or None)."""
    writer = _parent_writer.get()
    if writer is not None:
        return writer
    try:
        return get_stream_writer()
    except RuntimeError:
        return None


@contextmanager
def forward_to(writer):
    """Routes `emit` calls (e.g. from a nested subgraph) to `writer`."""
    token = _parent_writer.set(writer)
    try:
        yield
    finally:
        _parent_writer.reset(token)


def emit(stage: str, language: str = "id", **detail) -> None:
    """Sends `{type: progress, stage, label, ...detail}`; no-op outside a streaming run."""
    writer = current_writer()
    if writer is None:
        return
    label = LABELS.get(stage, {}).get(language) or LABELS.get(stage, {}).get("en") or stage
    writer({"type": "progress", "stage": stage, "label": label, **detail})
