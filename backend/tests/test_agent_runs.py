"""Every LLM agent call is recorded in `agent_runs` (trace per chat turn / supplier message) and browsable."""
from datetime import datetime, timedelta, timezone

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.chatbot import tracing
from app.chatbot.service import ChatService
from app.config import settings
from app.database import SessionLocal
from app.models import AgentRun
from configs.workflows.chat_graph import build_graph
from tests import chat_fakes as F
from tests import po_helpers as H

API = "/api/v1/agent-runs"


def _chat(script: dict) -> ChatService:
    agents, _, registry = F.fake_agents({"PromptRewriterOutput": F.REWRITE, "RouterOutput": F.ROUTE_AUTO, **script})
    return ChatService(build_graph(agents, registry.chatbot, checkpointer=InMemorySaver(),
                                   automation_cfg=registry.automation))


def _runs() -> list[AgentRun]:
    with SessionLocal() as db:
        return list(db.scalars(select(AgentRun).options(undefer(AgentRun.input), undefer(AgentRun.system_prompt),
                                                        undefer(AgentRun.attempts)).order_by(AgentRun.id)))


def test_chat_turn_is_one_trace_with_every_agent_call(seeded):
    svc = _chat({"AutomationParserOutput": F.parsed(items=[F.item("Ban Dalam", 10)])})
    svc.run("Buat PO 10 ban dalam", "thread-trace-1")
    runs = _runs()
    assert [r.agent for r in runs] == ["prompt_rewriter", "router", "automation_parser"]
    assert {r.trace_id for r in runs} == {runs[0].trace_id} and {r.workflow for r in runs} == {"chat"}
    assert all(r.status == "ok" and r.ref == {"thread_id": "thread-trace-1"} for r in runs)
    parser = runs[-1]
    assert parser.output["items"][0]["material_query"] == "Ban Dalam" and '"latest_message"' in parser.input
    assert "PURCHASE ORDER change request" in parser.system_prompt and len(parser.attempts) == 1
    svc.run("Buat PO 10 ban dalam", "thread-trace-1")
    assert len({r.trace_id for r in _runs()}) == 2                     # giliran berikutnya = trace baru


def test_invalid_output_is_recorded_with_both_attempts(seeded):
    svc = _chat({"RouterOutput": {"intent": "nonsense"}})
    assert svc.run("halo", "thread-trace-2")["type"] == "error"
    router = next(r for r in _runs() if r.agent == "router")
    assert router.status == "invalid" and len(router.attempts) == 2 and "intent" in router.error
    assert router.output is None


def test_supplier_reply_is_traced_with_its_conversation(seeded):
    po_id = H.issue_po(seeded, "RM-TUB-01", "SUP-KRT", 5)
    svc, _ = H.supplier_service({"SupplierOutreachOutput": F.OUTREACH, "SupplierReplyOutput": F.reply("confirmed")})
    chat = H.link(svc, seeded, "SUP-KRT")
    cid = H.start(svc, po_id)
    svc.handle_inbound(chat, "siap")
    outreach = next(r for r in _runs() if r.agent == "supplier_outreach_writer")
    reply = next(r for r in _runs() if r.agent == "supplier_reply_agent")
    assert outreach.workflow == "supplier_outreach"
    assert reply.workflow == "supplier" and reply.ref["conversation_id"] == cid and reply.ref["chat_id"] == chat


def test_api_filters_and_detail(client, seeded):
    svc = _chat({"AutomationParserOutput": F.parsed(items=[F.item("Ban Dalam", 10)])})
    svc.run("Buat PO 10 ban dalam", "thread-trace-3")
    page = client.get(API, params={"agent": "router"}).json()
    assert page["total"] == 1 and page["items"][0]["agent"] == "router" and "system_prompt" not in page["items"][0]
    trace = page["items"][0]["trace_id"]
    steps = client.get(API, params={"trace_id": trace}).json()["items"]
    assert [s["agent"] for s in steps] == ["prompt_rewriter", "router", "automation_parser"]   # urut waktu
    assert client.get(API, params={"q": "Ban Dalam", "agent": "automation_parser"}).json()["total"] == 1
    assert client.get(API, params={"status": "invalid"}).json()["total"] == 0
    detail = client.get(f"{API}/{steps[-1]['id']}").json()
    assert detail["system_prompt"] and detail["attempts"][0]["errors"] == [] and detail["retries"] == 0
    facets = client.get(f"{API}/facets").json()
    assert {"value": "chat", "count": 3} in facets["workflows"]
    assert client.get(f"{API}/999999").status_code == 404


def test_tracing_can_be_disabled(seeded, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_TRACE_ENABLED", False)
    _chat({"AutomationParserOutput": F.parsed(items=[F.item("Ban Dalam", 10)])}).run("Buat PO 10 ban dalam", "t-4")
    assert _runs() == []


def test_purge_removes_old_runs(seeded):
    old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=40)
    with SessionLocal() as db:
        db.add_all([AgentRun(agent="router", trace_id="a", status="ok", input="x", created_at=old),
                    AgentRun(agent="router", trace_id="b", status="ok", input="y")])
        db.commit()
    assert tracing.purge_old(30) == 1 and [r.trace_id for r in _runs()] == ["b"]
