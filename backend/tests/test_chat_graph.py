"""LangGraph flows with scripted LLMs against the real (test) database."""
import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.api.v1.endpoints import chat as chat_endpoint
from app.chatbot.service import ChatService
from configs.workflows.chat_graph import build_graph
from configs.workflows.sql_agent_graph import build_sql_graph
from tests import chat_fakes as F
from tests.test_flow_e2e import _schedule_two_days

ANSWER = {"blocks": [F.text_block("There are 2 critical items: Ban Luar Karet and Rangka Besi Dudukan Jok."),
                     F.table_block("E1", ["sku", "name", "available", "status"])],
          "claims": [{"text": "2 critical items", "evidence_ids": ["E1"]}], "insufficient_data": False}


def _service(script):
    agents, fake, registry = F.fake_agents(script)
    graph = build_graph(agents, registry.chatbot, checkpointer=InMemorySaver())
    return ChatService(graph), fake


def _script(**overrides):
    base = {"PromptRewriterOutput": F.REWRITE, "RouterOutput": F.ROUTE_MRP,
            "RetrievalPlannerOutput": F.PLAN_CRITICAL, "SynthesizerOutput": ANSWER,
            "EvaluatorOutput": F.judge()}
    return {**base, **overrides}


@pytest.fixture()
def critical_state(client, seeded):
    _schedule_two_days(client, seeded["BIKE"])
    return seeded


def test_happy_path_streams_progress_and_grounded_table(critical_state):
    svc, fake = _service(_script())
    events = list(svc.stream("item apa yang critical?", "thread-happy"))
    stages = [e["stage"] for e in events if e["type"] == "progress"]
    assert stages[:4] == ["rewrite", "route", "plan", "tool"]
    assert "synthesize" in stages and "evaluate" in stages
    final = events[-1]
    assert final["type"] == "final"
    text, table = final["blocks"]
    assert text["type"] == "text"
    assert table["type"] == "table" and len(table["rows"]) == 2
    assert [r[0] for r in table["rows"]] == ["RM-RUB-01", "RM-SBR-01"]
    meta = final["meta"]
    assert meta["passed"] and meta["score"] >= 0.8 and meta["metrics"]["numeric_grounding"] == 1.0
    assert meta["sources"][0]["tool"] == "get_critical_items"
    assert fake.count("EvaluatorOutput") == 1


def test_low_score_triggers_revision_with_critique(critical_state):
    svc, fake = _service(_script(EvaluatorOutput=[
        F.judge(f=0.4, failure="unfaithful", critique="Claim about Pedal is unsupported", supported=False),
        F.judge()]))
    final = svc.run("item apa yang critical?", "thread-revise")
    assert final["meta"]["passed"] and final["meta"]["attempts"]["revise"] == 1
    assert fake.count("SynthesizerOutput") == 2
    second = json.loads([c for c in fake.calls if c["agent"] == "SynthesizerOutput"][1]["messages"][-1]["content"])
    assert "Pedal is unsupported" in second["critique_from_previous_evaluation"]


def test_missing_context_triggers_new_retrieval(critical_state):
    plan2 = {"calls": [{"tool": "get_material_suppliers", "purpose": "suppliers",
                        "args": F.args(material="Ban Luar Karet")}]}
    svc, fake = _service(_script(
        RetrievalPlannerOutput=[F.PLAN_CRITICAL, plan2],
        EvaluatorOutput=[F.judge(r=0.5, c=0.2, failure="missing_context", critique="Supplier data missing"),
                         F.judge()]))
    final = svc.run("critical items and who supplies them?", "thread-replan")
    assert fake.count("RetrievalPlannerOutput") == 2
    assert [s["tool"] for s in final["meta"]["sources"]] == ["get_critical_items", "get_material_suppliers"]
    assert final["meta"]["passed"] and final["meta"]["attempts"]["retrieve"] == 2


def test_exhausted_attempts_return_best_draft_with_low_confidence_notice(critical_state):
    svc, fake = _service(_script(EvaluatorOutput=F.judge(f=0.3, r=0.5, c=0.5, failure="unfaithful",
                                                          supported=False)))
    final = svc.run("item apa yang critical?", "thread-exhaust")
    assert fake.count("SynthesizerOutput") == 3
    assert final["meta"]["passed"] is False
    assert final["blocks"][-1]["type"] == "notice"


def test_ungrounded_number_lowers_numeric_score(critical_state):
    bad = {**ANSWER, "blocks": [F.text_block("There are 7 critical items.")]}
    svc, _ = _service(_script(SynthesizerOutput=bad))
    final = svc.run("item apa yang critical?", "thread-numeric")
    assert final["meta"]["metrics"]["numeric_grounding"] == 0.0


def test_smalltalk_skips_retrieval_and_evaluation(seeded):
    svc, fake = _service(_script(RouterOutput={"intent": "smalltalk", "reason": "greeting"},
                                 DirectResponderOutput={"blocks": [{"type": "text", "text": "Halo!"}]}))
    final = svc.run("halo", "thread-smalltalk")
    assert final["blocks"] == [{"type": "text", "text": "Halo!"}]
    assert final["meta"]["evaluated"] is False
    assert fake.count("RetrievalPlannerOutput") == 0 and fake.count("EvaluatorOutput") == 0


def test_follow_up_turn_receives_history(critical_state):
    svc, fake = _service(_script())
    svc.run("item apa yang critical?", "thread-follow")
    svc.run("siapa supplier termurahnya?", "thread-follow")
    rewrites = [json.loads(c["messages"][-1]["content"]) for c in fake.calls if c["agent"] == "PromptRewriterOutput"]
    assert rewrites[0]["conversation_history"] == []
    assert [m["role"] for m in rewrites[1]["conversation_history"]] == ["user", "assistant"]
    assert "Ban Luar Karet" in rewrites[1]["conversation_history"][1]["content"]
    history = svc.history("thread-follow")
    assert [m["role"] for m in history] == ["user", "agent", "user", "agent"]
    assert history[1]["blocks"][1]["type"] == "table"


def test_query_database_tool_repairs_failed_sql(critical_state):
    plan = {"calls": [{"tool": "query_database", "purpose": "count by status",
                       "args": F.args(question="How many items per stock status?")}]}
    svc, fake = _service(_script(
        RetrievalPlannerOutput=plan,
        SqlGeneratorOutput={"sql": "SELECT stat, COUNT(*) FROM chat_inventory_status_v GROUP BY stat",
                            "tables_used": ["chat_inventory_status_v"], "rationale": "x"},
        SqlFixerOutput={"sql": "SELECT status, COUNT(*) AS n FROM chat_inventory_status_v GROUP BY status "
                               "ORDER BY status", "diagnosis": "column is status", "give_up": False},
        SynthesizerOutput={"blocks": [F.text_block("2 items are critical."), F.table_block("E1", ["status", "n"])],
                           "claims": [], "insufficient_data": False}))
    events = list(svc.stream("berapa item per status?", "thread-sql"))
    assert "sql_fix" in [e.get("stage") for e in events]
    final = events[-1]
    src = final["meta"]["sources"][0]
    assert src["tool"] == "query_database" and src["error"] is None and "LIMIT" in src["sql"]
    assert {r[0]: r[1] for r in final["blocks"][1]["rows"]}["CRITICAL"] == "2"


def test_sql_agent_gives_up_after_max_attempts():
    agents, fake, registry = F.fake_agents({
        "SqlGeneratorOutput": {"sql": "DELETE FROM materials", "tables_used": [], "rationale": "x"},
        "SqlFixerOutput": {"sql": "DROP TABLE materials", "diagnosis": "x", "give_up": False}})
    graph = build_sql_graph(agents, max_attempts=3, row_limit=200, timeout_ms=5000)
    out = graph.invoke({"question": "q", "language": "en"})
    assert out["attempts"] == 3 and out["error"].startswith("Rejected by SQL guard")
    assert fake.count("SqlFixerOutput") == 2


def test_sse_endpoint_streams_events(client, critical_state):
    svc, _ = _service(_script())
    client.app.dependency_overrides[chat_endpoint.service] = lambda: svc
    with client.stream("POST", "/api/v1/chat/stream",
                       json={"message": "item critical?", "thread_id": "thread-sse-01"}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = [json.loads(chunk.split("data: ", 1)[1]) for chunk in body.strip().split("\n\n")]
    assert events[0]["type"] == "progress" and events[-1]["type"] == "final"
    hist = client.get("/api/v1/chat/thread-sse-01/history").json()
    assert len(hist["messages"]) == 2


def test_chat_returns_503_when_not_configured(client, monkeypatch):
    from app.chatbot import service as service_module
    monkeypatch.setattr(service_module, "_service", None)
    monkeypatch.setattr(service_module.settings, "AICORE_BASE_URL", None)
    r = client.post("/api/v1/chat", json={"message": "halo", "thread_id": "thread-503-x"})
    assert r.status_code == 503 and "AICORE" in r.json()["detail"]
    assert client.get("/api/v1/chat/health").json() == {"configured": False}


def test_postgres_checkpointer_persists_conversation(critical_state):
    import uuid
    from app.chatbot.service import _checkpointer
    thread = f"thread-pg-{uuid.uuid4().hex[:12]}"
    agents, _, registry = F.fake_agents(_script())
    saver = _checkpointer()
    try:
        svc = ChatService(build_graph(agents, registry.chatbot, checkpointer=saver))
        assert svc.run("item apa yang critical?", thread)["type"] == "final"
        reloaded = ChatService(build_graph(agents, registry.chatbot, checkpointer=saver))
        history = reloaded.history(thread)
        assert [m["role"] for m in history] == ["user", "agent"]
        assert history[1]["meta"]["passed"] is True
    finally:
        saver.conn.close()


def test_chat_returns_503_when_sap_connection_fails(client, monkeypatch):
    from app.chatbot import service as service_module

    def boom(*_a, **_k):
        raise RuntimeError("Bad credentials")

    monkeypatch.setattr(service_module, "_service", None)
    for key in ("AICORE_AUTH_URL", "AICORE_CLIENT_ID", "AICORE_CLIENT_SECRET", "AICORE_BASE_URL"):
        monkeypatch.setattr(service_module.settings, key, "x")
    monkeypatch.setattr(service_module, "build_sap_clients", boom)
    r = client.post("/api/v1/chat", json={"message": "halo", "thread_id": "thread-503-y"})
    assert r.status_code == 503 and "Bad credentials" in r.json()["detail"]
