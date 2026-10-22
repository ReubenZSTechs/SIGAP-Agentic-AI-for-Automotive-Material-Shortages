"""query_database agent: LangGraph subgraph that writes, guards, runs and repairs SQL.

    generate (LLM) -> guard (sqlglot: read-only, allowed tables, LIMIT) -> execute (read-only connection)
                         ^                                                   │ error / 0 rows
                         └────────────────────── fix (LLM) <─────────────────┘   (at most `max_attempts` runs)
"""
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


EMPTY_RESULT = "Query returned 0 rows"


class SqlAgentWorkflow:
    """Text-to-SQL loop; one method per node."""

    def __init__(self, agents: dict[str, Agent], *, max_attempts: int, row_limit: int, timeout_ms: int):
        self.agents = agents
        self.max_attempts = max_attempts
        self.row_limit = row_limit
        self.timeout_ms = timeout_ms
        self.prompt_vars = {"schema_catalog": catalog_text(), "row_limit": row_limit}

    def generate(self, state: SqlState) -> SqlState:
        """LLM writes the first SQL for the question."""
        emit("sql_generate", state.get("language", "id"))
        out = self.agents["sql_generator"].run(state["question"], today=date.today().isoformat(), **self.prompt_vars)
        return {"sql": out["sql"], "attempts": 0, "trail": []}

    def guard(self, state: SqlState) -> SqlState:
        """Static check: one read-only SELECT over allowed relations, with a LIMIT."""
        try:
            return {"sql": validate_sql(state["sql"], ALLOWED_RELATIONS, self.row_limit), "error": None}
        except SqlGuardError as e:
            return {"error": f"Rejected by SQL guard: {e}"}

    def execute(self, state: SqlState) -> SqlState:
        """Runs the SQL (skipped when the guard rejected it); an empty result is retried once."""
        attempts = state.get("attempts", 0) + 1
        trail = [*state.get("trail", []), {"sql": state["sql"], "error": state.get("error")}]
        if state.get("error"):
            return {"attempts": attempts, "trail": trail}
        emit("sql_execute", state.get("language", "id"), attempt=attempts)
        try:
            columns, rows = run_select(state["sql"], self.timeout_ms)
        except SqlExecutionError as e:
            trail[-1]["error"] = str(e)
            return {"attempts": attempts, "error": f"Database error: {e}", "trail": trail}
        if not rows and not state.get("retried_empty"):
            trail[-1]["error"] = "0 rows"
            return {"attempts": attempts, "columns": columns, "rows": [], "trail": trail,
                    "error": f"{EMPTY_RESULT}; check whether filters are too strict."}
        return {"attempts": attempts, "columns": columns, "rows": rows, "error": None, "trail": trail}

    def fix(self, state: SqlState) -> SqlState:
        """LLM repairs the SQL using the error and the previous attempts (or gives up)."""
        emit("sql_fix", state.get("language", "id"), attempt=state["attempts"])
        payload = {"question": state["question"], "previous_sql": state["sql"], "error": state["error"],
                   "previous_attempts": state.get("trail", [])}
        out = self.agents["sql_fixer"].run(json.dumps(payload, ensure_ascii=False),
                                           today=date.today().isoformat(), **self.prompt_vars)
        empty = (state.get("error") or "").startswith(EMPTY_RESULT)
        if out["give_up"] or not out["sql"]:
            return {"give_up": True, "error": f"Gave up: {out['diagnosis']}"}
        return {"sql": out["sql"], "error": None, "retried_empty": state.get("retried_empty") or empty}

    @staticmethod
    def accept_empty(_: SqlState) -> SqlState:
        """Out of attempts but the query itself worked: an empty result is a valid answer."""
        return {"error": None}

    # ------------------------------------------------------------ edges & wiring
    def next_after_execute(self, state: SqlState) -> str:
        if not state.get("error"):
            return END
        if state["attempts"] >= self.max_attempts:
            empty = (state["error"] or "").startswith(EMPTY_RESULT)
            return "accept_empty" if empty else END
        return "fix"

    @staticmethod
    def next_after_fix(state: SqlState) -> str:
        return END if state.get("give_up") else "guard"

    def compile(self):
        g = StateGraph(SqlState)
        for name in ("generate", "guard", "execute", "fix", "accept_empty"):
            g.add_node(name, getattr(self, name))
        g.add_edge(START, "generate")
        g.add_edge("generate", "guard")
        g.add_edge("guard", "execute")
        g.add_conditional_edges("execute", self.next_after_execute, ["fix", "accept_empty", END])
        g.add_conditional_edges("fix", self.next_after_fix, ["guard", END])
        g.add_edge("accept_empty", END)
        return g.compile()


def build_sql_graph(agents: dict[str, Agent], *, max_attempts: int, row_limit: int, timeout_ms: int):
    """Compiled query_database subgraph (see `SqlAgentWorkflow`)."""
    return SqlAgentWorkflow(agents, max_attempts=max_attempts, row_limit=row_limit, timeout_ms=timeout_ms).compile()
