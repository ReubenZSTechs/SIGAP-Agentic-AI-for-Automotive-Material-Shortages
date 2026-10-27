"""Riwayat percakapan chatbot: daftar per browser, buka ulang, hapus satu/semua."""
import uuid
from datetime import timedelta

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select, text

from app.api.v1.endpoints import chat as chat_endpoint
from app.chatbot import threads
from app.chatbot.service import ChatService
from app.database import SessionLocal
from app.models import AutomationAction
from app.models.chat_thread import ChatThread, utcnow
from app.models.enums import AutomationOperation, AutomationStatus
from configs.workflows.chat_graph import build_graph
from tests import chat_fakes as F

API = "/api/v1/chat"
ME, OTHER = "browser-me-0001", "browser-other-02"
SMALLTALK = {"PromptRewriterOutput": F.REWRITE, "RouterOutput": {"intent": "smalltalk", "reason": "greeting"},
             "DirectResponderOutput": {"blocks": [{"type": "text", "text": "Halo!"}]}}


def _service(checkpointer=None) -> ChatService:
    agents, _, registry = F.fake_agents(SMALLTALK)
    return ChatService(build_graph(agents, registry.chatbot, checkpointer=checkpointer or InMemorySaver()))


@pytest.fixture()
def svc(client):
    service = _service()
    client.app.dependency_overrides[chat_endpoint.service] = lambda: service
    return service


def _list(client, owner=ME):
    r = client.get(f"{API}/threads", headers={"X-Client-Id": owner})
    assert r.status_code == 200, r.text
    return r.json()["threads"]


def _delete(client, thread_id, owner=ME):
    return client.delete(f"{API}/threads/{thread_id}", headers={"X-Client-Id": owner})


def _set_updated(thread_id, **delta):
    with SessionLocal() as db:
        row = db.get(ChatThread, thread_id)
        row.updated_at = utcnow() + timedelta(**delta)
        db.commit()


# ------------------------------------------------------------------ daftar
def test_first_message_creates_an_entry_titled_after_it(client, svc):
    svc.run("  Ringkas stok\n\n saat ini   ", "thread-first-01", owner=ME)
    [row] = _list(client)
    assert row["thread_id"] == "thread-first-01" and row["title"] == "Ringkas stok saat ini"
    assert row["created_at"] and row["updated_at"]


def test_follow_up_keeps_the_title_and_moves_the_thread_to_the_top(client, svc):
    svc.run("pertanyaan pertama A", "thread-order-a1", owner=ME)
    svc.run("pertanyaan pertama B", "thread-order-b1", owner=ME)
    _set_updated("thread-order-a1", hours=-2)                    # A lebih lama dari B
    assert [r["thread_id"] for r in _list(client)] == ["thread-order-b1", "thread-order-a1"]
    svc.run("lanjutan untuk A", "thread-order-a1", owner=ME)
    rows = _list(client)
    assert [r["thread_id"] for r in rows] == ["thread-order-a1", "thread-order-b1"]
    assert rows[0]["title"] == "pertanyaan pertama A"             # judul tetap dari pesan pertama


def test_long_titles_are_trimmed():
    assert threads.make_title("x" * 200) == "x" * 59 + "…"
    assert len(threads.make_title("kata " * 60)) <= threads.TITLE_MAX
    assert threads.make_title("   \n ") == "Percakapan"


def test_list_only_shows_this_browsers_conversations(client, svc):
    svc.run("milik saya", "thread-mine-001", owner=ME)
    svc.run("milik orang lain", "thread-theirs-01", owner=OTHER)
    svc.run("tanpa pemilik", "thread-nobody-01")                  # klien tanpa header
    assert [r["thread_id"] for r in _list(client, ME)] == ["thread-mine-001"]
    assert [r["thread_id"] for r in _list(client, OTHER)] == ["thread-theirs-01"]


def test_list_and_delete_require_the_client_header(client, svc):
    assert client.get(f"{API}/threads").status_code == 422
    assert client.delete(f"{API}/threads").status_code == 422
    assert client.delete(f"{API}/threads/thread-any-0001").status_code == 422
    assert client.get(f"{API}/threads", headers={"X-Client-Id": "short"}).status_code == 422   # format id


def test_stream_endpoint_records_the_owner_from_the_header(client, svc):
    with client.stream("POST", f"{API}/stream", headers={"X-Client-Id": ME},
                       json={"message": "halo dari SSE", "thread_id": "thread-sse-0001"}) as r:
        assert r.status_code == 200
        "".join(r.iter_text())
    assert [r["title"] for r in _list(client)] == ["halo dari SSE"]
    assert client.post(API, headers={"X-Client-Id": ME},
                       json={"message": "halo non-stream", "thread_id": "thread-json-0001"}).json()["type"] == "final"
    assert {r["title"] for r in _list(client)} == {"halo dari SSE", "halo non-stream"}


def test_ownerless_entry_is_adopted_but_an_owner_is_never_replaced(svc):
    svc.run("halo", "thread-adopt-001")                           # tanpa pemilik
    svc.run("halo lagi", "thread-adopt-001", owner=ME)            # klien pertama yang bicara mengambilnya
    svc.run("halo ketiga", "thread-adopt-001", owner=OTHER)       # pemilik tidak bisa direbut
    with SessionLocal() as db:
        assert db.get(ChatThread, "thread-adopt-001").owner_id == ME


def test_touch_never_creates_an_entry():
    with SessionLocal() as db:
        threads.touch(db, "thread-ghost-001")
        assert db.scalar(select(func.count()).select_from(ChatThread)) == 0


def test_a_history_bookkeeping_failure_never_breaks_the_chat(svc, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("db down")
    monkeypatch.setattr(threads, "register", boom)
    assert svc.run("halo", "thread-broken-01", owner=ME)["type"] == "final"
    assert [m["role"] for m in svc.history("thread-broken-01")] == ["user", "agent"]


# ------------------------------------------------------------------ buka ulang
def test_a_listed_conversation_can_be_reopened(client, svc):
    svc.run("halo pertama", "thread-open-0001", owner=ME)
    svc.run("halo kedua", "thread-open-0001", owner=ME)
    [row] = _list(client)
    hist = client.get(f"{API}/{row['thread_id']}/history").json()
    assert [m["role"] for m in hist["messages"]] == ["user", "agent", "user", "agent"]
    assert hist["messages"][0]["blocks"] == [{"type": "text", "text": "halo pertama"}]


# ------------------------------------------------------------------ hapus
def test_delete_removes_messages_and_the_list_entry(client, svc):
    svc.run("halo", "thread-del-00001", owner=ME)
    svc.run("halo", "thread-keep-0001", owner=ME)
    assert _delete(client, "thread-del-00001").status_code == 204
    assert [r["thread_id"] for r in _list(client)] == ["thread-keep-0001"]
    assert client.get(f"{API}/thread-del-00001/history").json()["messages"] == []
    assert len(client.get(f"{API}/thread-keep-0001/history").json()["messages"]) == 2     # yang lain utuh
    assert _delete(client, "thread-del-00001").status_code == 404                          # sudah hilang


def test_someone_elses_conversation_cannot_be_deleted(client, svc):
    svc.run("rahasia", "thread-theirs-02", owner=OTHER)
    r = _delete(client, "thread-theirs-02", owner=ME)
    assert r.status_code == 404 and r.json()["detail"] == "Percakapan tidak ditemukan"
    assert len(svc.history("thread-theirs-02")) == 2 and len(_list(client, OTHER)) == 1


def test_delete_all_only_clears_this_browser(client, svc):
    for i in range(3):
        svc.run("halo", f"thread-mine-{i:04d}", owner=ME)
    svc.run("halo", "thread-theirs-03", owner=OTHER)
    svc.run("halo", "thread-nobody-02")
    r = client.delete(f"{API}/threads", headers={"X-Client-Id": ME})
    assert r.status_code == 200 and r.json() == {"deleted": 3}
    assert _list(client) == []
    assert [x["thread_id"] for x in _list(client, OTHER)] == ["thread-theirs-03"]
    assert len(svc.history("thread-theirs-03")) == 2 and len(svc.history("thread-nobody-02")) == 2
    assert client.delete(f"{API}/threads", headers={"X-Client-Id": ME}).json() == {"deleted": 0}


def test_delete_closes_a_waiting_proposal_but_keeps_the_audit_trail(client, svc):
    svc.run("halo", "thread-audit-001", owner=ME)

    def action(status):
        return AutomationAction(id=uuid.uuid4().hex, thread_id="thread-audit-001", operation=AutomationOperation.CREATE,
                                status=status, proposal={}, expires_at=utcnow() + timedelta(hours=1))
    waiting, done, other = action(AutomationStatus.PROPOSED), action(AutomationStatus.EXECUTED), action(AutomationStatus.PROPOSED)
    other.thread_id = "thread-other-001"
    waiting_id, done_id, other_id = waiting.id, done.id, other.id
    with SessionLocal() as db:
        db.add_all([waiting, done, other])
        db.commit()
    assert _delete(client, "thread-audit-001").status_code == 204
    with SessionLocal() as db:
        assert db.get(AutomationAction, waiting_id).status == AutomationStatus.SUPERSEDED
        assert db.get(AutomationAction, waiting_id).decided_at is not None
        assert db.get(AutomationAction, done_id).status == AutomationStatus.EXECUTED       # catatan bisnis tetap
        assert db.get(AutomationAction, other_id).status == AutomationStatus.PROPOSED      # thread lain tak tersentuh


def test_postgres_delete_wipes_every_checkpoint_table(client):
    """Dengan checkpointer Postgres sungguhan: tidak ada sisa di checkpoints / blobs / writes."""
    from app.chatbot.service import _checkpointer
    saver = _checkpointer()
    try:
        svc = _service(saver)
        client.app.dependency_overrides[chat_endpoint.service] = lambda: svc
        thread = f"thread-pg-{uuid.uuid4().hex[:12]}"
        svc.run("halo", thread, owner=ME)
        svc.run("halo lagi", thread, owner=ME)

        def rows(table):
            with SessionLocal() as db:
                return db.scalar(text(f"SELECT count(*) FROM {table} WHERE thread_id = :t"), {"t": thread})
        assert rows("checkpoints") > 0 and rows("checkpoint_blobs") > 0
        assert _delete(client, thread).status_code == 204
        assert (rows("checkpoints"), rows("checkpoint_blobs"), rows("checkpoint_writes")) == (0, 0, 0)
        assert svc.history(thread) == [] and _list(client) == []
    finally:
        saver.conn.close()
