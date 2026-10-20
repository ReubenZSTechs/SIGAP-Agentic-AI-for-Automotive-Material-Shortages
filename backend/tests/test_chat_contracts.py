"""Agent output contracts (JSON Schemas) and deterministic scoring."""
import json

import pytest
from jsonschema import Draft202012Validator

from app.chatbot.config_loader import CONFIG_DIR, load_registry
from app.chatbot.llm import Agent, AgentOutputError, strict_schema
from app.chatbot.scoring import apply_gate, extract_numbers, numeric_grounding
from tests import chat_fakes as F

FIXTURES = {
    "prompt_rewriter": F.REWRITE,
    "router": F.ROUTE_MRP,
    "retrieval_planner": F.PLAN_CRITICAL,
    "sql_generator": {"sql": "SELECT 1", "tables_used": [], "rationale": "x"},
    "sql_fixer": {"sql": None, "diagnosis": "no data", "give_up": True},
    "synthesizer": {"blocks": [F.text_block("x"), F.table_block("E1", ["sku"])],
                    "claims": [{"text": "x", "evidence_ids": ["E1"]}], "insufficient_data": False},
    "evaluator": F.judge(),
    "direct_responder": {"blocks": [{"type": "text", "text": "Halo"}]},
    "automation_parser": F.parsed(items=[F.item("ban", 50)]),
    "automation_clarifier": F.clarify(options=[{"label": "RM-RUB-01 Ban Luar Karet", "value": "RM-RUB-01"}]),
    "supplier_outreach_writer": F.OUTREACH,
    "mission_reply_agent": {"decision": "answered", "reply_text": "Terima kasih.", "promised_date": None,
                            "items": [{"material_ref": "RM-PDL-01", "price_per_unit": 41000, "lead_time_days": 4,
                                       "qty_available": None, "ready_date": None}],
                            "documents_promised": False, "confidence": "HIGH", "notes": None},
    "supplier_reply_agent": F.reply("change_requested", changes=[F.change("RM-RUB-01", "qty", "40")]),
    "supplier_inbound_triage": F.triage("PO-202610-0001", "revision_request"),
    "manager_escalation_writer": F.ESCALATION,
    "manager_decision_agent": F.decision(cr_id=1),
}


def test_every_agent_has_a_valid_schema_and_fixture():
    registry = load_registry()
    assert set(registry.agents) == set(FIXTURES)
    for name, spec in registry.agents.items():
        Draft202012Validator.check_schema(spec.schema)
        assert (CONFIG_DIR / "schema" / f"{name}.schema.json").exists()
        assert not list(spec.validator.iter_errors(FIXTURES[name])), name


def test_strict_schema_keeps_structure_and_drops_unsupported_keywords():
    for spec in load_registry().agents.values():
        s = json.dumps(strict_schema(spec.schema))
        assert "minLength" not in s and "$schema" not in s
        assert strict_schema(spec.schema)["required"] == spec.schema["required"]

    def check(node):
        if isinstance(node, dict):
            if "properties" in node:
                assert sorted(node["properties"]) == sorted(node["required"])
                assert node.get("additionalProperties") is False
            for v in node.values():
                check(v)
        elif isinstance(node, list):
            for v in node:
                check(v)

    for spec in load_registry().agents.values():
        check(strict_schema(spec.schema))


def _router(responses):
    spec = load_registry().agents["router"]
    return Agent(spec, F.FakeLLM({spec.schema["title"]: responses}))


def test_agent_retries_once_then_succeeds():
    agent = _router(['{"intent": "nonsense"}', '```json\n{"intent": "smalltalk", "reason": "hi"}\n```'])
    assert agent.run("halo")["intent"] == "smalltalk"
    assert len(agent.client.calls) == 2
    assert "did not match the JSON Schema" in agent.client.calls[1]["messages"][-1]["content"]


def test_agent_raises_after_second_invalid_output():
    agent = _router(["not json", '{"intent": "smalltalk"}'])
    with pytest.raises(AgentOutputError, match="router"):
        agent.run("halo")


def test_extract_numbers_ignores_codes_dates_and_evidence_ids():
    text = "RM-PDL-01 punya 3 supplier [E1], harga Rp 42.500 sejak 2026-10-12, PO-2026-0001."
    assert extract_numbers(text) == ["3", "42.500"]


def _ev(rows):
    return [{"id": "E1", "tool": "t", "args": {}, "purpose": "", "columns": list(rows[0]), "rows": rows,
             "row_count": len(rows), "truncated": False, "meta": {}, "sql": None, "error": None}]


def test_numeric_grounding_accepts_values_counts_and_sums():
    ev = _ev([{"sku": "A", "status": "CRITICAL", "price": 3400000, "qty": 1.5},
              {"sku": "B", "status": "CRITICAL", "price": 100, "qty": 2},
              {"sku": "C", "status": "SAFE", "price": 5, "qty": 0}])
    score, bad = numeric_grounding("Ada 2 item critical dari 3; total Rp 3.400.105, qty 1,5 dan 3.5", ev)
    assert (score, bad) == (1.0, [])
    score, bad = numeric_grounding("Harga 999 dan qty 2", ev)
    assert bad == ["999"] and score == 0.5


def test_gate_weighting_and_faithfulness_floor():
    w = {"faithfulness": 0.4, "answer_relevance": 0.25, "numeric_grounding": 0.2, "completeness": 0.15}
    ok = apply_gate({"faithfulness": 0.9, "answer_relevance": 0.8, "numeric_grounding": 1, "completeness": 0.6},
                    w, 0.8, 0.7)
    assert ok.passed and ok.score == pytest.approx(0.85)
    floor = apply_gate({"faithfulness": 0.6, "answer_relevance": 1, "numeric_grounding": 1, "completeness": 1},
                       w, 0.5, 0.7)
    assert not floor.passed
    low = apply_gate({"faithfulness": 0.8, "answer_relevance": 0.7, "numeric_grounding": 0.8, "completeness": 0.7},
                     w, 0.8, 0.7)
    assert not low.passed and low.score < 0.8
