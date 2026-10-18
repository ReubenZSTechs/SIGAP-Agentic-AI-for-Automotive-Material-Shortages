"""query_database agent: LangGraph subgraph that writes, guards, runs and repairs SQL."""
import json
from datetime import date
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.chatbot.llm import Agent
from app.chatbot.progress import emit
from app.chatbot.schema_catalog import ALLOWED_RELATIONS, catalog_text
from configs.tools.sql_executor import SqlExecutionError, run_select
from configs.tools.sql_guard import SqlGuardError, validate_sql


class SqlState(TypedDict, total=False):
    """State of one query_database call."""
    question: str
    language: str
    sql: str | None
    error: str | None
    columns: list[str]
    rows: list[dict]
    attempts: int
    retried_empty: bool
    give_up: bool
    trail: list[dict]


def build_sql_graph(agents: dict[str, Agent], *, max_attempts: int, row_limit: int,
                    timeout_ms: int):
    """Compiles the generate -> guard -> execute -> fix loop (at most `max_attempts` executions)."""
    prompt_vars = {"schema_catalog": catalog_text(), "row_limit": row_limit}

    def generate(state: SqlState) -> SqlState:
        emit("sql_generate", state.get("language", "id"))
        out = agents["sql_generator"].run(state["question"], today=date.today().isoformat(), **prompt_vars)
        return {"sql": out["sql"], "attempts": 0, "trail": []}

    def guard(state: SqlState) -> SqlState:
        try:
            return {"sql": validate_sql(state["sql"], ALLOWED_RELATIONS, row_limit), "error": None}
        except SqlGuardError as e:
            return {"error": f"Rejected by SQL guard: {e}"}

    def execute(state: SqlState) -> SqlState:
        attempts = state.get("attempts", 0) + 1
        trail = [*state.get("trail", []), {"sql": state["sql"], "error": state.get("error")}]
        if state.get("error"):
            return {"attempts": attempts, "trail": trail}
        emit("sql_execute", state.get("language", "id"), attempt=attempts)
        try:
            columns, rows = run_select(state["sql"], timeout_ms)
        except SqlExecutionError as e:
            trail[-1]["error"] = str(e)
            return {"attempts": attempts, "error": f"Database error: {e}", "trail": trail}
        if not rows and not state.get("retried_empty"):
            trail[-1]["error"] = "0 rows"
            return {"attempts": attempts, "columns": columns, "rows": [], "trail": trail,
                    "error": "Query returned 0 rows; check whether filters are too strict."}
        return {"attempts": attempts, "columns": columns, "rows": rows, "error": None, "trail": trail}

    def fix(state: SqlState) -> SqlState:
        emit("sql_fix", state.get("language", "id"), attempt=state["attempts"])
        payload = {"question": state["question"], "previous_sql": state["sql"], "error": state["error"],
                   "previous_attempts": state.get("trail", [])}
        out = agents["sql_fixer"].run(json.dumps(payload, ensure_ascii=False),
                                      today=date.today().isoformat(), **prompt_vars)
        empty = (state.get("error") or "").startswith("Query returned 0 rows")
        if out["give_up"] or not out["sql"]:
            return {"give_up": True, "error": f"Gave up: {out['diagnosis']}"}
        return {"sql": out["sql"], "error": None, "retried_empty": state.get("retried_empty") or empty}

    def after_execute(state: SqlState) -> str:
        if not state.get("error"):
            return END
        if state["attempts"] >= max_attempts:
            empty = (state["error"] or "").startswith("Query returned 0 rows")
            return "accept_empty" if empty else END
        return "fix"

    def accept_empty(_: SqlState) -> SqlState:
        return {"error": None}

    def after_fix(state: SqlState) -> str:
        return END if state.get("give_up") else "guard"

    g = StateGraph(SqlState)
    g.add_node("generate", generate)
    g.add_node("guard", guard)
    g.add_node("execute", execute)
    g.add_node("fix", fix)
    g.add_node("accept_empty", accept_empty)
    g.add_edge(START, "generate")
    g.add_edge("generate", "guard")
    g.add_edge("guard", "execute")
    g.add_conditional_edges("execute", after_execute, ["fix", "accept_empty", END])
    g.add_conditional_edges("fix", after_fix, ["guard", END])
    g.add_edge("accept_empty", END)
    return g.compile()
