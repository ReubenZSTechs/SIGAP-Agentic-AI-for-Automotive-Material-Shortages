"""Scripted LLM doubles for chatbot tests (keyed by the agent schema `title`)."""
import json

from app.chatbot.config_loader import load_registry
from app.chatbot.llm import build_agents


class FakeLLM:
    """Returns scripted outputs per agent schema title; each entry is a dict, a str, or a callable.

    A list of entries is consumed in order; the last entry repeats once the list is exhausted.
    """

    def __init__(self, script: dict):
        self.script = {k: (v if isinstance(v, list) else [v]) for k, v in script.items()}
        self.calls: list[dict] = []

    def complete(self, *, system, messages, schema, generation):
        title = schema["title"]
        self.calls.append({"agent": title, "system": system, "messages": messages})
        queue = self.script[title]
        entry = queue.pop(0) if len(queue) > 1 else queue[0]
        if callable(entry):
            entry = entry(json.loads(messages[-1]["content"]) if messages[-1]["content"].startswith("{")
                          else messages[-1]["content"])
        return entry

    def count(self, title: str) -> int:
        return sum(1 for c in self.calls if c["agent"] == title)


def fake_agents(script: dict):
    """All registered agents bound to one `FakeLLM`."""
    fake = FakeLLM(script)
    registry = load_registry()
    return build_agents(registry, {key: fake for key in registry.models}), fake, registry


def args(**kw) -> dict:
    """Planner args object with every key present (unused keys null), as the schema requires."""
    keys = ["category", "status", "include_warning", "query", "material", "supplier", "product",
            "qty", "date_from", "date_to", "schedule_status", "question"]
    return {k: kw.get(k) for k in keys}


REWRITE = {"rewritten_query": "Which items have critical stock?", "language": "en", "is_follow_up": False}
ROUTE_MRP = {"intent": "mrp_query", "reason": "asks about stock"}
PLAN_CRITICAL = {"calls": [{"tool": "get_critical_items", "purpose": "critical items",
                            "args": args(include_warning=False)}]}


def text_block(text: str) -> dict:
    return {"type": "text", "text": text, "evidence_id": None, "columns": None, "title": None}


def table_block(eid: str, columns: list[str]) -> dict:
    return {"type": "table", "text": None, "evidence_id": eid, "columns": columns, "title": None}


def judge(f=1.0, r=1.0, c=1.0, failure="none", critique="ok", supported=True) -> dict:
    return {"faithfulness": f, "answer_relevance": r, "completeness": c,
            "claim_verdicts": [{"claim": "c1", "supported": supported, "evidence_ids": ["E1"], "note": ""}],
            "failure_type": failure, "critique": critique}
