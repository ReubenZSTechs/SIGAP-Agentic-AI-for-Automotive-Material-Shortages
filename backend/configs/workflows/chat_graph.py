"""Main chat workflow (LangGraph). One user message = one run of this graph.

    rewrite -> route ─┬─ mrp_query ──> plan -> execute_tools -> synthesize -> evaluate ─┬─> finalize
                      │                  ^                         ^                    │
                      │                  └──── replan ─────────────┴──── revise ────────┘
                      ├─ po_automation ─> PO branch           (automation_graph.py)
                      ├─ master_data ───> new data form branch (master_data_graph.py)
                      └─ other ─────────> respond_direct -> finalize

Each node is a method of `ChatWorkflow`: it receives the current state and returns only the fields it changes.
"""
import contextvars
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.chatbot.evidence import Evidence, evidence_prompt, filter_rows, filtered_evidence, make_evidence, render_table
from app.chatbot.llm import Agent
from app.chatbot.progress import current_writer, emit, forward_to
from app.chatbot.scoring import apply_gate, numeric_grounding
from configs.tools.curated import CURATED
from configs.tools.registry import catalog_text, run_curated, run_query_database
from configs.workflows.automation_graph import PoAutomationWorkflow
from configs.workflows.master_data_graph import MasterDataWorkflow
from configs.workflows.sql_agent_graph import build_sql_graph

LANGUAGE_NAMES = {"id": "Indonesian (Bahasa Indonesia)", "en": "English"}

LOW_CONFIDENCE = {
    "id": "Catatan: jawaban ini belum lolos verifikasi kualitas (skor {score:.2f} < {threshold:.2f}). "
          "Mohon cek ulang angka di halaman terkait sebelum mengambil keputusan.",
    "en": "Note: this answer did not pass quality verification (score {score:.2f} < {threshold:.2f}). "
          "Please double-check the figures on the related page before acting on them.",
}

ERROR_TEXT = {
    "id": "Maaf, saya belum bisa memproses permintaan ini. Silakan coba lagi.",
    "en": "Sorry, I could not process this request. Please try again.",
}


class ChatState(TypedDict, total=False):
    """Graph state. `messages` and `automation_draft` persist across turns; the rest is reset every turn."""
    messages: Annotated[list[AnyMessage], add_messages]
    thread_id: str
    question: str
    forced_language: str | None          # language chosen in the UI ("id"/"en"); None = detect
    rewritten: str
    language: str
    intent: str
    plan: list[dict]
    evidence: list[Evidence]
    draft: dict | None
    evaluation: dict | None
    best: dict | None
    feedback: str | None
    next_step: str
    retrieve_attempts: int
    revise_attempts: int
    final: dict | None
    # PO automation (see automation_graph.py)
    automation_draft: dict | None        # request being collected across clarification turns
    automation_resolution: dict | None
    automation_step: str
    automation_decision: dict | None     # value the confirmation interrupt was resumed with
    pending_action: dict | None
    # Master data: new product / material / supplier (see master_data_graph.py)
    master_draft: dict | None            # form being filled across turns: {entity, values, errors, proposal?}
    master_step: str
    master_decision: dict | None         # value a form/confirmation interrupt was resumed with


def new_turn(message: str, thread_id: str = "", language: str | None = None) -> ChatState:
    """Input for a new user turn (resets every per-turn field; keeps `automation_draft` and `master_draft`).

    `language` = the UI language the user picked; when given, it is used instead of the detected one.
    """
    return ChatState(messages=[HumanMessage(content=message)], question=message, rewritten=message,
                     language=language or "id", forced_language=language, intent="", plan=[], evidence=[], draft=None, evaluation=None,
                     best=None, feedback=None, next_step="", retrieve_attempts=0, revise_attempts=0,
                     final=None, thread_id=thread_id, automation_resolution=None, automation_step="",
                     automation_decision=None, pending_action=None, master_step="", master_decision=None)


def _card_summary(card: dict) -> str:
    """One line per PO proposal card, so later turns can refer to what it proposed."""
    parts = []
    for t in card.get("tables") or []:
        rows = "; ".join(" ".join(str(c) for c in r[:3]) for r in t.get("rows") or [])
        parts.append(f"{t.get('title', '')}: {rows}")
    return f"[Kartu usulan PO: {card.get('title', '')} — " + " | ".join(parts) + "]"


def _history(messages: list[AnyMessage], turns: int) -> list[dict]:
    """Previous turns (excluding the latest user message) as plain role/content dicts.

    PO proposal cards are only in `additional_kwargs`, so their content is appended as a summary line.
    """
    out = []
    for m in messages[:-1]:
        if isinstance(m, HumanMessage):
            out.append({"role": "user", "content": str(m.content)})
        elif isinstance(m, AIMessage):
            cards = [_card_summary(c) for c in (m.additional_kwargs.get("actions") or {}).values()]
            out.append({"role": "assistant", "content": "\n".join([str(m.content), *cards])})
    return out[-turns * 2:]


def _answer_text(blocks: list[dict]) -> str:
    return "\n".join(b["text"] for b in blocks if b.get("type") == "text" and b.get("text"))


def _call_key(tool: str, args: dict) -> str:
    return json.dumps([tool, {k: v for k, v in sorted(args.items()) if v is not None}], default=str)


class ChatWorkflow:
    """Builds the chat graph. `cfg` / `automation_cfg` are sections of models.yaml.

    `on_supplier_work` is called after an automation queued supplier conversations (starts Telegram dispatch).
    """

    def __init__(self, agents: dict[str, Agent], cfg: dict, automation_cfg: dict | None = None,
                 on_supplier_work=None):
        self.agents = agents
        self.cfg = cfg
        self.automation_cfg = automation_cfg or {}
        self.on_supplier_work = on_supplier_work
        self.evidence_cfg = cfg["evidence"]
        self.gate_cfg = cfg["evaluation"]
        sql_cfg = cfg["sql_agent"]
        self.row_limit = sql_cfg["row_limit"]
        self.sql_graph = build_sql_graph(agents, max_attempts=sql_cfg["max_attempts"], row_limit=self.row_limit,
                                         timeout_ms=sql_cfg["statement_timeout_ms"])

    # ------------------------------------------------------------ 1. understand the message
    def rewrite(self, state: ChatState) -> ChatState:
        """Standalone English query + language detection (resolves follow-up references)."""
        emit("rewrite", state.get("forced_language") or "id")      # bahasa UI sudah diketahui sebelum deteksi
        payload = {"conversation_history": _history(state["messages"], self.cfg.get("history_turns", 6)),
                   "latest_message": state["question"]}
        out = self.agents["prompt_rewriter"].run(json.dumps(payload, ensure_ascii=False))
        return {"rewritten": out["rewritten_query"], "language": state.get("forced_language") or out["language"]}

    def route(self, state: ChatState) -> ChatState:
        """Classifies intent: `mrp_query` -> retrieval, `po_automation` -> PO branch, `master_data` -> form branch."""
        emit("route", state["language"])
        pending = state.get("automation_draft")
        pending_info = None
        if pending:
            pending_info = {"request": pending["request"],
                            "last_question": (pending.get("last_clarification") or {}).get("question")}
        master = state.get("master_draft")
        master_info = {"entity": master["entity"], "values": master.get("values")} if master else None
        payload = {"message": state["question"], "rewritten": state["rewritten"],
                   "pending_po_request": pending_info, "pending_master_form": master_info}
        out = self.agents["router"].run(json.dumps(payload, ensure_ascii=False, default=str))
        update = {"intent": out["intent"]}
        if pending and out["intent"] != "po_automation":   # pengguna beralih topik -> draf dibuang
            update["automation_draft"] = None
        if master and out["intent"] != "master_data":
            update["master_draft"] = None
        return update

    def respond_direct(self, state: ChatState) -> ChatState:
        """Replies to smalltalk / out-of-scope / write requests without touching data."""
        emit("respond", state["language"])
        out = self.agents["direct_responder"].run(state["question"], intent=state["intent"],
                                                  language_name=LANGUAGE_NAMES[state["language"]])
        return {"draft": {"blocks": out["blocks"], "claims": [], "insufficient_data": False}}

    # ------------------------------------------------------------ 2. fetch data
    def plan(self, state: ChatState) -> ChatState:
        """Chooses tool calls, skipping calls already made this turn."""
        emit("plan", state["language"])
        max_calls = self.evidence_cfg["max_calls_per_plan"]
        fetched = [{"id": e["id"], "tool": e["tool"], "args": e["args"], "row_count": e["row_count"],
                    "error": e["error"]} for e in state.get("evidence", [])]
        payload = {"question": state["rewritten"], "original_message": state["question"],
                   "already_fetched": fetched, "feedback": state.get("feedback")}
        out = self.agents["retrieval_planner"].run(json.dumps(payload, ensure_ascii=False),
                                                   tool_catalog=catalog_text(), today=date.today().isoformat(),
                                                   max_calls=max_calls)
        seen = {_call_key(e["tool"], e["args"]) for e in state.get("evidence", [])}
        calls = []
        for c in out["calls"][:max_calls]:
            key = _call_key(c["tool"], c["args"])
            if key not in seen:
                seen.add(key)
                calls.append(c)
        return {"plan": calls, "retrieve_attempts": state.get("retrieve_attempts", 0) + 1}

    def _run_tool(self, call: dict, eid: str, language: str, writer) -> Evidence:
        """Runs one planned tool call and returns its result as evidence `eid`."""
        args = {k: v for k, v in call["args"].items() if v is not None}
        emit("tool", language, tool=call["tool"], evidence_id=eid)
        if call["tool"] == "query_database":
            with forward_to(writer):                       # progress of the SQL subgraph goes to this chat
                return run_query_database(self.sql_graph, args, call["purpose"], eid, language, self.row_limit)
        if call["tool"] not in CURATED:
            return make_evidence(eid, call["tool"], args, call["purpose"], [], row_limit=self.row_limit,
                                 error="Unknown tool")
        return run_curated(call["tool"], args, call["purpose"], eid, self.row_limit)

    def execute_tools(self, state: ChatState) -> ChatState:
        """Runs planned calls concurrently (max 4 at once) and appends their results as evidence."""
        existing = list(state.get("evidence", []))
        calls = state.get("plan", [])
        if not calls:
            return {"evidence": existing}
        ids = [f"E{len(existing) + i + 1}" for i in range(len(calls))]
        writer = current_writer()
        with ThreadPoolExecutor(max_workers=min(4, len(calls))) as pool:
            # copy_context(): each thread keeps the trace / progress context of this chat turn
            futures = [pool.submit(contextvars.copy_context().run, self._run_tool, c, eid, state["language"], writer)
                       for c, eid in zip(calls, ids)]
            new = [f.result() for f in futures]
        return {"evidence": existing + new}

    # ------------------------------------------------------------ 3. answer and check the answer
    def synthesize(self, state: ChatState) -> ChatState:
        """Drafts a grounded answer; table blocks only reference evidence ids."""
        revising = bool(state.get("draft")) and state.get("next_step") == "revise"
        emit("revise" if revising else "synthesize", state["language"])
        payload = {"question": state["rewritten"], "original_message": state["question"],
                   "evidence": evidence_prompt(state["evidence"], self.evidence_cfg["max_rows_in_prompt"])}
        if state.get("feedback"):
            payload["critique_from_previous_evaluation"] = state["feedback"]
            if state.get("draft"):
                payload["previous_answer"] = state["draft"]
        out = self.agents["synthesizer"].run(json.dumps(payload, ensure_ascii=False),
                                             language_name=LANGUAGE_NAMES[state["language"]])
        known = {e["id"] for e in state["evidence"]}
        blocks = [b for b in out["blocks"]
                  if (b["type"] == "text" and b.get("text")) or (b["type"] == "table" and b.get("evidence_id") in known)]
        if not blocks:
            blocks = [{"type": "text", "text": ERROR_TEXT[state["language"]], "evidence_id": None, "columns": None,
                       "title": None, "filters": None}]
        return {"draft": {**out, "blocks": blocks}}

    def _judge(self, state: ChatState) -> tuple[dict, dict]:
        """LLM judge + deterministic numeric check -> (judge output, evaluation with the weighted gate)."""
        draft, evidence = state["draft"], state["evidence"]
        text = _answer_text(draft["blocks"])
        ev_by_id = {e["id"]: e for e in evidence}
        tables = [{"evidence_id": b["evidence_id"], "columns": b.get("columns"), "filters": b.get("filters"),
                   "rows_shown": len(filter_rows(ev_by_id[b["evidence_id"]], b.get("filters")))}
                  for b in draft["blocks"] if b["type"] == "table" and b.get("evidence_id") in ev_by_id]
        shown = [filtered_evidence(ev_by_id[t["evidence_id"]], t["filters"]) for t in tables if t["filters"]]
        payload = {"question": state["rewritten"], "original_message": state["question"],
                   "evidence": evidence_prompt(evidence, self.evidence_cfg["max_rows_in_prompt"]),
                   "answer": {"text": text, "tables_rendered_from_evidence": tables,
                              "claims": draft.get("claims", [])}}
        judge = self.agents["evaluator"].run(json.dumps(payload, ensure_ascii=False))
        verdicts = judge["claim_verdicts"]
        faithfulness = (sum(v["supported"] for v in verdicts) / len(verdicts)) if verdicts else judge["faithfulness"]
        numeric, ungrounded = numeric_grounding(text, evidence + shown, state["question"])
        metrics = {"faithfulness": faithfulness, "answer_relevance": judge["answer_relevance"],
                   "numeric_grounding": numeric, "completeness": judge["completeness"]}
        gate = apply_gate(metrics, self.gate_cfg["weights"], self.gate_cfg["threshold"],
                          self.gate_cfg["faithfulness_floor"])
        evaluation = {"score": gate.score, "passed": gate.passed, "metrics": gate.metrics,
                      "failure_type": judge["failure_type"], "critique": judge["critique"],
                      "ungrounded_numbers": ungrounded}
        return judge, evaluation

    def _next_step(self, state: ChatState, evaluation: dict) -> str:
        """finalize (passed or out of attempts) | replan (missing data) | revise (rewrite the answer)."""
        if evaluation["passed"]:
            return "finalize"
        if evaluation["failure_type"] == "missing_context" and \
                state["retrieve_attempts"] < self.gate_cfg["max_retrieve_attempts"]:
            return "replan"
        if state.get("revise_attempts", 0) < self.gate_cfg["max_revise_attempts"]:
            return "revise"
        return "finalize"

    def evaluate(self, state: ChatState) -> ChatState:
        """Scores the draft, keeps the best draft so far, and decides the next step."""
        emit("evaluate", state["language"])
        judge, evaluation = self._judge(state)
        emit("evaluate", state["language"], score=evaluation["score"], passed=evaluation["passed"])
        best = state.get("best")
        if best is None or evaluation["score"] > best["evaluation"]["score"]:
            best = {"draft": state["draft"], "evaluation": evaluation}
        critique = judge["critique"]
        if evaluation["ungrounded_numbers"]:
            critique += f" Numbers not found in evidence: {', '.join(evaluation['ungrounded_numbers'])}."
        step = self._next_step(state, evaluation)
        update = {"evaluation": evaluation, "best": best, "next_step": step, "feedback": critique}
        if step == "revise":
            update["revise_attempts"] = state.get("revise_attempts", 0) + 1
        return update

    # ------------------------------------------------------------ 4. reply
    def finalize(self, state: ChatState) -> ChatState:
        """Renders the best draft into frontend blocks and appends it to the conversation."""
        language = state["language"]
        evaluated = state.get("evaluation") is not None
        chosen = state.get("best") if evaluated else {"draft": state["draft"], "evaluation": None}
        if evaluated and state["evaluation"]["passed"]:
            chosen = {"draft": state["draft"], "evaluation": state["evaluation"]}
        evidence = {e["id"]: e for e in state.get("evidence", [])}
        blocks = []
        for b in chosen["draft"]["blocks"]:
            if b["type"] == "table":
                blocks.append(render_table(evidence[b["evidence_id"]], b.get("columns"), language, b.get("title"),
                                           b.get("filters")))
            elif b["type"] == "text":
                blocks.append({"type": "text", "text": b["text"]})
            else:                                               # options (klarifikasi otomasi PO), dll.
                blocks.append(b)
        ev = chosen["evaluation"]
        if ev and not ev["passed"]:
            blocks.append({"type": "notice", "tone": "warning",
                           "text": LOW_CONFIDENCE[language].format(score=ev["score"],
                                                                   threshold=self.gate_cfg["threshold"])})
        meta = {
            "intent": state.get("intent"),
            "language": language,
            "rewritten_question": state.get("rewritten"),
            "evaluated": evaluated,
            "threshold": self.gate_cfg["threshold"],
            "score": ev["score"] if ev else None,
            "passed": ev["passed"] if ev else None,
            "metrics": ev["metrics"] if ev else None,
            "attempts": {"retrieve": state.get("retrieve_attempts", 0), "revise": state.get("revise_attempts", 0)},
            "sources": [{"id": e["id"], "tool": e["tool"], "args": e["args"], "row_count": e["row_count"],
                         "sql": e["sql"], "error": e["error"]} for e in evidence.values()],
        }
        final = {"blocks": blocks, "meta": meta}
        message = AIMessage(content=_answer_text(blocks), additional_kwargs={"blocks": blocks, "meta": meta})
        return {"final": final, "messages": [message]}

    # ------------------------------------------------------------ edges (which node runs next)
    @staticmethod
    def next_after_route(state: ChatState) -> str:
        branches = {"mrp_query": "plan", "po_automation": "auto_parse", "master_data": "master_parse"}
        return branches.get(state["intent"], "respond_direct")

    @staticmethod
    def next_after_evaluate(state: ChatState) -> str:
        return {"replan": "plan", "revise": "synthesize"}.get(state["next_step"], "finalize")

    # ------------------------------------------------------------ wiring
    def compile(self, checkpointer=None):
        g = StateGraph(ChatState)
        for name in ("rewrite", "route", "respond_direct", "plan", "execute_tools", "synthesize", "evaluate",
                     "finalize"):
            g.add_node(name, getattr(self, name))
        PoAutomationWorkflow(self.agents, self.automation_cfg, on_supplier_work=self.on_supplier_work).add_to(g)
        MasterDataWorkflow(self.agents, self.automation_cfg).add_to(g)

        g.add_edge(START, "rewrite")
        g.add_edge("rewrite", "route")
        g.add_conditional_edges("route", self.next_after_route,
                                ["plan", "auto_parse", "master_parse", "respond_direct"])
        g.add_edge("respond_direct", "finalize")
        g.add_edge("plan", "execute_tools")
        g.add_edge("execute_tools", "synthesize")
        g.add_edge("synthesize", "evaluate")
        g.add_conditional_edges("evaluate", self.next_after_evaluate, ["plan", "synthesize", "finalize"])
        g.add_edge("finalize", END)
        return g.compile(checkpointer=checkpointer)


def build_graph(agents: dict[str, Agent], cfg: dict, checkpointer=None, automation_cfg: dict | None = None,
                on_supplier_work=None):
    """Compiled chat graph (see `ChatWorkflow`)."""
    return ChatWorkflow(agents, cfg, automation_cfg, on_supplier_work).compile(checkpointer)
