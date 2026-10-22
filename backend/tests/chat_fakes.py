"""Scripted LLM doubles for chatbot tests (keyed by the agent schema `title`)."""
import json
from datetime import date, timedelta

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


# ------------------------------ PO automation & supplier Telegram ------------------------------
ROUTE_AUTO = {"intent": "po_automation", "reason": "asks to change a PO"}


def parsed(operation="create", items=None, po_reference=None, supplier_query=None, needed_by_date=None,
           notes=None, user_cancelled=False, is_new_request=False) -> dict:
    """AutomationParserOutput with every key present."""
    return {"operation": operation, "po_reference": po_reference, "items": items or [],
            "supplier_query": supplier_query, "needed_by_date": needed_by_date, "notes": notes,
            "is_new_request": is_new_request, "user_cancelled": user_cancelled, "reason": "test"}


def item(material_query: str, qty=None) -> dict:
    return {"material_query": material_query, "qty": qty}


def clarify(question="Material yang mana?", options=None) -> dict:
    return {"question_text": question, "options": options or []}


OUTREACH = {"message_text": "Halo, mohon konfirmasi PO berikut.", "language": "id"}


SOON = (date.today() + timedelta(days=7)).isoformat()      # tanggal kirim valid untuk konfirmasi lengkap


def reply(decision="confirmed", text="Terima kasih.", promised=None, ref=None, changes=None, summary=None) -> dict:
    """SupplierReplyOutput."""
    return {"decision": decision, "reply_text": text, "promised_delivery_date": promised, "supplier_reference": ref,
            "proposed_changes": changes or [], "change_summary": summary, "reason": "test"}


def change(material_ref: str, field: str, new_value: str) -> dict:
    return {"material_ref": material_ref, "field": field, "new_value": new_value, "reason": None}


def triage(po_number=None, intent="other", text="Baik.", promised=None) -> dict:
    return {"po_number": po_number, "intent": intent, "reply_text": text, "promised_delivery_date": promised}


ESCALATION = {"message_text": "Supplier perlu ditindaklanjuti.", "urgency": "normal",
              "recommended_option": "none", "rationale": "test"}


def decision(choice="approve_change", cr_id=None, text="Siap.") -> dict:
    return {"choice": choice, "change_request_id": cr_id, "reply_text": text}


# ------------------------------ Master data (produk / material / supplier baru) ------------------------------
ROUTE_MASTER = {"intent": "master_data", "reason": "asks to add new master data"}
MASTER_FIELDS = ("sku", "code", "name", "uom", "selling_price", "specification", "contact", "payment_term_days",
                 "initial_stock", "safety_stock")


def master(entity="product", items=None, user_cancelled=False, is_new_request=False, **fields) -> dict:
    """MasterDataParserOutput with every key present."""
    return {"entity": entity, "is_new_request": is_new_request, "user_cancelled": user_cancelled,
            "fields": {k: fields.get(k) for k in MASTER_FIELDS}, "items": items or [], "reason": "test"}


def master_item(query: str, qty=None, unit_price=None, lead_time_days=None, moq=None) -> dict:
    return {"query": query, "qty": qty, "unit_price": unit_price, "lead_time_days": lead_time_days, "moq": moq}
