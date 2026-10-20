"""Main LangGraph workflow: rewrite -> route -> plan -> tools -> synthesize -> evaluate (loop) -> finalize.

PO change requests (`po_automation`) branch into `automation_graph` (clarify -> confirm -> execute).
"""
import contextvars
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.chatbot.evidence import Evidence, evidence_prompt, make_evidence, render_table
from app.chatbot.llm import Agent
from app.chatbot.progress import current_writer, emit, forward_to
from app.chatbot.scoring import apply_gate, numeric_grounding
from configs.tools.curated import CURATED
from configs.tools.registry import catalog_text, run_curated, run_query_database
from configs.workflows.automation_graph import add_automation_nodes
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


def new_turn(message: str, thread_id: str = "") -> ChatState:
    """Input for a new user turn (resets every per-turn field; keeps `automation_draft`)."""
    return ChatState(messages=[HumanMessage(content=message)], question=message, rewritten=message,
                     language="id", intent="", plan=[], evidence=[], draft=None, evaluation=None,
                     best=None, feedback=None, next_step="", retrieve_attempts=0, revise_attempts=0,
                     final=None, thread_id=thread_id, automation_resolution=None, automation_step="",
                     automation_decision=None, pending_action=None)


def _history(messages: list[AnyMessage], turns: int) -> list[dict]:
    """Previous turns (excluding the latest user message) as plain role/content dicts."""
    out = [{"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": str(m.content)}
           for m in messages[:-1] if isinstance(m, (HumanMessage, AIMessage))]
    return out[-turns * 2:]


def _answer_text(blocks: list[dict]) -> str:
    return "\n".join(b["text"] for b in blocks if b.get("type") == "text" and b.get("text"))


def _call_key(tool: str, args: dict) -> str:
    return json.dumps([tool, {k: v for k, v in sorted(args.items()) if v is not None}], default=str)


def build_graph(agents: dict[str, Agent], cfg: dict, checkpointer=None, automation_cfg: dict | None = None,
                on_supplier_work=None):
    """Compiles the chatbot graph. `cfg` / `automation_cfg` are sections of models.yaml.

    `on_supplier_work` is called after an automation queued supplier conversations (starts Telegram dispatch).
    """
    ev_cfg, sql_cfg, gate_cfg = cfg["evidence"], cfg["sql_agent"], cfg["evaluation"]
    row_limit = sql_cfg["row_limit"]
    sql_graph = build_sql_graph(agents, max_attempts=sql_cfg["max_attempts"], row_limit=row_limit,
                                timeout_ms=sql_cfg["statement_timeout_ms"])

    def rewrite(state: ChatState) -> ChatState:
        """Standalone English query + language detection (resolves follow-up references)."""
        emit("rewrite")
        payload = {"conversation_history": _history(state["messages"], cfg.get("history_turns", 6)),
                   "latest_message": state["question"]}
        out = agents["prompt_rewriter"].run(json.dumps(payload, ensure_ascii=False))
        return {"rewritten": out["rewritten_query"], "language": out["language"]}

    def route(state: ChatState) -> ChatState:
        """Classifies intent: `mrp_query` -> retrieval, `po_automation` -> automation branch."""
        emit("route", state["language"])
        pending = state.get("automation_draft")
        pending_info = {"request": pending["request"], "last_question": (pending.get("last_clarification") or {})
                        .get("question")} if pending else None
        out = agents["router"].run(json.dumps({"message": state["question"], "rewritten": state["rewritten"],
                                               "pending_po_request": pending_info}, ensure_ascii=False))
        update = {"intent": out["intent"]}
        if pending and out["intent"] != "po_automation":   # pengguna beralih topik -> draf dibuang
            update["automation_draft"] = None
        return update

    def respond_direct(state: ChatState) -> ChatState:
        """Replies to smalltalk / out-of-scope / write requests without touching data."""
        emit("respond", state["language"])
        out = agents["direct_responder"].run(state["question"], intent=state["intent"],
                                             language_name=LANGUAGE_NAMES[state["language"]])
        return {"draft": {"blocks": out["blocks"], "claims": [], "insufficient_data": False}}

    def plan(state: ChatState) -> ChatState:
        """Chooses tool calls, skipping calls already made this turn."""
        emit("plan", state["language"])
        fetched = [{"id": e["id"], "tool": e["tool"], "args": e["args"], "row_count": e["row_count"],
                    "error": e["error"]} for e in state.get("evidence", [])]
        payload = {"question": state["rewritten"], "original_message": state["question"],
                   "already_fetched": fetched, "feedback": state.get("feedback")}
        out = agents["retrieval_planner"].run(json.dumps(payload, ensure_ascii=False),
                                              tool_catalog=catalog_text(), today=date.today().isoformat(),
                                              max_calls=ev_cfg["max_calls_per_plan"])
        seen = {_call_key(e["tool"], e["args"]) for e in state.get("evidence", [])}
        calls = []
        for c in out["calls"][:ev_cfg["max_calls_per_plan"]]:
            key = _call_key(c["tool"], c["args"])
            if key not in seen:
                seen.add(key)
                calls.append(c)
        return {"plan": calls, "retrieve_attempts": state.get("retrieve_attempts", 0) + 1}

    def execute_tools(state: ChatState) -> ChatState:
        """Runs planned calls concurrently and appends their results as evidence."""
        existing = list(state.get("evidence", []))
        language = state["language"]
        writer = current_writer()

        def run(call: dict, eid: str) -> Evidence:
            args = {k: v for k, v in call["args"].items() if v is not None}
            emit("tool", language, tool=call["tool"], evidence_id=eid)
            if call["tool"] == "query_database":
                with forward_to(writer):
                    return run_query_database(sql_graph, args, call["purpose"], eid, language, row_limit)
            if call["tool"] not in CURATED:
                return make_evidence(eid, call["tool"], args, call["purpose"], [], row_limit=row_limit,
                                     error="Unknown tool")
            return run_curated(call["tool"], args, call["purpose"], eid, row_limit)

        calls = state.get("plan", [])
        ids = [f"E{len(existing) + i + 1}" for i in range(len(calls))]
        if not calls:
            return {"evidence": existing}
        with ThreadPoolExecutor(max_workers=min(4, len(calls))) as pool:
            futures = [pool.submit(contextvars.copy_context().run, run, c, eid) for c, eid in zip(calls, ids)]
            new = [f.result() for f in futures]
        return {"evidence": existing + new}

    def synthesize(state: ChatState) -> ChatState:
        """Drafts a grounded answer; table blocks only reference evidence ids."""
        revising = bool(state.get("draft")) and state.get("next_step") == "revise"
        emit("revise" if revising else "synthesize", state["language"])
        payload = {"question": state["rewritten"], "original_message": state["question"],
                   "evidence": evidence_prompt(state["evidence"], ev_cfg["max_rows_in_prompt"])}
        if state.get("feedback"):
            payload["critique_from_previous_evaluation"] = state["feedback"]
            if state.get("draft"):
                payload["previous_answer"] = state["draft"]
        out = agents["synthesizer"].run(json.dumps(payload, ensure_ascii=False),
                                        language_name=LANGUAGE_NAMES[state["language"]])
        known = {e["id"] for e in state["evidence"]}
        blocks = [b for b in out["blocks"]
                  if (b["type"] == "text" and b.get("text")) or (b["type"] == "table" and b.get("evidence_id") in known)]
        return {"draft": {**out, "blocks": blocks or [{"type": "text", "text": ERROR_TEXT[state["language"]],
                                                       "evidence_id": None, "columns": None, "title": None}]}}

    def evaluate(state: ChatState) -> ChatState:
        """LLM judge + deterministic numeric check, weighted gate, and next-step decision."""
        emit("evaluate", state["language"])
        draft, evidence = state["draft"], state["evidence"]
        text = _answer_text(draft["blocks"])
        tables = [{"evidence_id": b["evidence_id"], "columns": b.get("columns")}
                  for b in draft["blocks"] if b["type"] == "table"]
        payload = {"question": state["rewritten"], "original_message": state["question"],
                   "evidence": evidence_prompt(evidence, ev_cfg["max_rows_in_prompt"]),
                   "answer": {"text": text, "tables_rendered_from_evidence": tables,
                              "claims": draft.get("claims", [])}}
        judge = agents["evaluator"].run(json.dumps(payload, ensure_ascii=False))
        verdicts = judge["claim_verdicts"]
        faithfulness = (sum(v["supported"] for v in verdicts) / len(verdicts)) if verdicts else judge["faithfulness"]
        numeric, ungrounded = numeric_grounding(text, evidence, state["question"])
        metrics = {"faithfulness": faithfulness, "answer_relevance": judge["answer_relevance"],
                   "numeric_grounding": numeric, "completeness": judge["completeness"]}
        gate = apply_gate(metrics, gate_cfg["weights"], gate_cfg["threshold"], gate_cfg["faithfulness_floor"])
        evaluation = {"score": gate.score, "passed": gate.passed, "metrics": gate.metrics,
                      "failure_type": judge["failure_type"], "critique": judge["critique"],
                      "ungrounded_numbers": ungrounded}
        emit("evaluate", state["language"], score=gate.score, passed=gate.passed)

        best = state.get("best")
        if best is None or gate.score > best["evaluation"]["score"]:
            best = {"draft": draft, "evaluation": evaluation}

        critique = judge["critique"]
        if ungrounded:
            critique += f" Numbers not found in evidence: {', '.join(ungrounded)}."
        if gate.passed:
            step = "finalize"
        elif judge["failure_type"] == "missing_context" and state["retrieve_attempts"] < gate_cfg["max_retrieve_attempts"]:
            step = "replan"
        elif state.get("revise_attempts", 0) < gate_cfg["max_revise_attempts"]:
            step = "revise"
        else:
            step = "finalize"
        update = {"evaluation": evaluation, "best": best, "next_step": step, "feedback": critique}
        if step == "revise":
            update["revise_attempts"] = state.get("revise_attempts", 0) + 1
        return update

    def finalize(state: ChatState) -> ChatState:
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
                blocks.append(render_table(evidence[b["evidence_id"]], b.get("columns"), language, b.get("title")))
            elif b["type"] == "text":
                blocks.append({"type": "text", "text": b["text"]})
            else:                                               # options (klarifikasi otomasi PO), dll.
                blocks.append(b)
        ev = chosen["evaluation"]
        if ev and not ev["passed"]:
            blocks.append({"type": "notice", "tone": "warning",
                           "text": LOW_CONFIDENCE[language].format(score=ev["score"], threshold=gate_cfg["threshold"])})
        meta = {
            "intent": state.get("intent"),
            "language": language,
            "rewritten_question": state.get("rewritten"),
            "evaluated": evaluated,
            "threshold": gate_cfg["threshold"],
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

    g = StateGraph(ChatState)
    for name, fn in [("rewrite", rewrite), ("route", route), ("respond_direct", respond_direct),
                     ("plan", plan), ("execute_tools", execute_tools), ("synthesize", synthesize),
                     ("evaluate", evaluate), ("finalize", finalize)]:
        g.add_node(name, fn)
    g.add_edge(START, "rewrite")
    g.add_edge("rewrite", "route")
    add_automation_nodes(g, agents, automation_cfg or {}, on_supplier_work=on_supplier_work)
    g.add_conditional_edges("route", lambda s: {"mrp_query": "plan", "po_automation": "auto_parse"}
                            .get(s["intent"], "respond_direct"), ["plan", "auto_parse", "respond_direct"])
    g.add_edge("respond_direct", "finalize")
    g.add_edge("plan", "execute_tools")
    g.add_edge("execute_tools", "synthesize")
    g.add_edge("synthesize", "evaluate")
    g.add_conditional_edges("evaluate", lambda s: {"replan": "plan", "revise": "synthesize"}.get(s["next_step"], "finalize"),
                            ["plan", "synthesize", "finalize"])
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
