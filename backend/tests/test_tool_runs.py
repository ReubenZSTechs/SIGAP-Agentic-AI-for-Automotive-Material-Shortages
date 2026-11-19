"""Every Postgres tool execution is recorded in `tool_runs` with its SQL, in the same trace as the agent calls."""
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.chatbot import tracing
from app.chatbot.service import ChatService
from app.database import SessionLocal
from app.models import AgentRun, ToolRun
from configs.tools.registry import run_curated
from configs.tools.sql_executor import SqlExecutionError, run_select
from configs.workflows.chat_graph import build_graph
from tests import chat_fakes as F

API = "/api/v1/tool-runs"


def _tool_runs() -> list[ToolRun]:
    with SessionLocal() as db:
        return list(db.scalars(select(ToolRun).options(undefer(ToolRun.statements), undefer(ToolRun.result_preview))
                               .order_by(ToolRun.id)))


def test_curated_tool_records_its_sql_and_rows(seeded):
    with tracing.trace_scope("chat", thread_id="t-tools-1"):
        ev = run_curated("find_materials", {"query": "Pedal"}, "find pedal", "E1", 50)
    assert ev["row_count"] == 1
    [run] = _tool_runs()
    assert (run.tool, run.kind, run.status, run.workflow, run.row_count) == ("find_materials", "read", "ok", "chat", 1)
    assert run.ref == {"thread_id": "t-tools-1"} and run.args == {"query": "Pedal"}
    assert run.statements and any("FROM materials" in s["sql"] for s in run.statements)
    assert run.result_preview[0]["sku"] == "RM-PDL-01"


def test_sql_agent_query_and_its_failure_are_recorded(seeded):
    run_select("SELECT sku FROM materials ORDER BY sku LIMIT 2", 5000)
    try:
        run_select("SELECT * FROM no_such_table", 5000)
    except SqlExecutionError:
        pass
    ok, failed = _tool_runs()
    assert ok.kind == "sql" and ok.row_count == 2 and ok.statements[-1]["sql"].startswith("SELECT sku")
    assert any("statement_timeout" in s["sql"] for s in ok.statements)
    assert failed.status == "error" and "no_such_table" in failed.error


def test_master_data_turn_traces_llm_calls_and_tool_runs_together(seeded):
    agents, _, registry = F.fake_agents({"PromptRewriterOutput": F.REWRITE, "RouterOutput": F.ROUTE_MASTER,
                                         "MasterDataParserOutput": F.master("supplier")})
    svc = ChatService(build_graph(agents, registry.chatbot, checkpointer=InMemorySaver(),
                                  automation_cfg=registry.automation))
    form = next(b for b in svc.run("supplier baru", "t-tools-2")["blocks"] if b["type"] == "form")
    card = svc.run(None, "t-tools-2", {"action_id": form["formId"], "decision": "submit",
                                       "values": {**form["values"], "code": "SUP-TRC", "name": "Trace"}})
    aid = next(b["actionId"] for b in card["blocks"] if b["type"] == "action")
    svc.run(None, "t-tools-2", {"action_id": aid, "decision": "approve"})
    runs = _tool_runs()
    assert [r.tool for r in runs] == ["apply_parsed", "validate_master_data", "execute_master_data"]
    write = runs[-1]
    assert write.kind == "write" and write.status == "ok"
    assert any(s["sql"].startswith("INSERT INTO suppliers") for s in write.statements)
    with SessionLocal() as db:
        first_turn = db.scalars(select(AgentRun.trace_id)).first()
    assert runs[0].trace_id == first_turn


def test_tool_runs_api_lists_filters_and_shows_detail(client, seeded):
    with tracing.trace_scope("chat", thread_id="t-tools-3") as trace:
        run_curated("list_suppliers", {"query": None}, "all", "E1", 50)
    run_curated("get_critical_items", {}, "critical", "E2", 50)
    listing = client.get(API, params={"trace_id": trace["trace_id"]}).json()
    assert listing["total"] == 1 and listing["items"][0]["tool"] == "list_suppliers"
    assert "statements" not in listing["items"][0]
    detail = client.get(f"{API}/{listing['items'][0]['id']}").json()
    assert detail["statements"] and len(detail["result_preview"]) > 0
    facets = client.get(f"{API}/facets").json()
    assert {f["value"] for f in facets["tools"]} == {"list_suppliers", "get_critical_items"}
    assert client.get(f"{API}/999999").status_code == 404
