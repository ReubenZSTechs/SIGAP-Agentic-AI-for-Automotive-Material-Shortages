"""Master-data branch of the chat graph: create a finished product, a purchased material or a supplier.

    master_parse ─┬─ cancelled / unclear ──────────────────────────────> finalize (text reply)
                  └─ entity known -> master_form -> master_await_form (interrupt: the user fills the form)
                                                        │
                       ┌──────── errors ── master_check <┘ submit        reject -> "dibatalkan"
                       v                        │ ok                     superseded (user typed instead)
                   master_form              master_propose                   -> draft kept for the next turn
                                                │
                                           master_await (interrupt: confirmation card)
                                                │
                                           master_execute (one transaction) -> result + links to the pages

Both pauses are LangGraph `interrupt()`s, saved by the checkpointer and resumed by `ChatService.stream(resume=...)`
with `{decision: submit|approve|reject|superseded, values?}`. Every rule lives in `configs/tools/master_actions.py`.
"""
import json
import logging
import uuid
from datetime import timedelta

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from app.chatbot import tracing
from app.chatbot.progress import emit
from app.core.i18n import translate_blocks, translate_card
from app.core.exceptions import AppError
from app.database import SessionLocal
from app.models import AutomationAction
from app.models.enums import AutomationOperation, AutomationStatus
from configs.tools import master_actions as M
from configs.tools import po_actions as A

log = logging.getLogger(__name__)
AS = AutomationStatus

UI_STATUS = {AS.PROPOSED: "pending", AS.EXECUTED: "approved", AS.REJECTED: "rejected",
             AS.SUPERSEDED: "expired", AS.EXPIRED: "expired", AS.FAILED: "failed"}

TEXT = {
    "ask_entity": "Data apa yang ingin Anda tambahkan?",
    "form_intro": "Silakan lengkapi formulir {title} berikut. Kolom bertanda * wajib diisi. Anda juga bisa "
                  "mengetik perubahannya di chat (mis. \"{example}\").",
    "form_errors": "Masih ada isian yang perlu diperbaiki (ditandai merah). Periksa lalu kirim lagi.",
    "propose": "Periksa data berikut. Belum ada yang disimpan sampai Anda menekan konfirmasi:",
    "cancelled": "Baik, penambahan data dibatalkan. Tidak ada data yang disimpan.",
    "rejected": "Baik, data tidak disimpan.",
    "expired": "Usulan ini sudah kedaluwarsa. Silakan kirim ulang permintaannya.",
    "failed": "Data gagal disimpan: {reason}. Tidak ada data yang berubah; ketik perbaikannya untuk membuka "
              "formulir lagi.",
}

TYPING_EXAMPLE = {"product": "tambahkan Rantai Sepeda 1 buah",
                  "material": "dari SUP-ASN harga 25 ribu, lead time 3 hari",
                  "supplier": "dia juga memasok Ban Dalam Karet harga 15 ribu"}

ENTITY_OPTIONS = [{"label": "Produk final baru", "value": "Saya ingin membuat produk final baru"},
                  {"label": "Material beli baru", "value": "Saya ingin menambah material beli baru"},
                  {"label": "Supplier baru", "value": "Saya ingin mendaftarkan supplier baru"}]


def _text_draft(*blocks: dict) -> dict:
    """A reply for the shared `finalize` node."""
    return {"blocks": list(blocks), "claims": [], "insufficient_data": False}


def _reply(blocks: list[dict], meta: dict, **extra) -> dict:
    """State update that shows `blocks` as this turn's answer (used by nodes that end the run themselves).

    Texts and cards are translated to the user's language (`meta["language"]`) here, in one place.
    """
    lang = meta.get("language")
    blocks = translate_blocks(blocks, lang)
    if "actions" in extra:
        extra["actions"] = {aid: translate_card(card, lang) for aid, card in extra["actions"].items()}
    text = "\n".join(b["text"] for b in blocks if b.get("type") == "text")
    final = {"blocks": blocks, "meta": meta, **extra}
    return {"final": final, "messages": [AIMessage(content=text, additional_kwargs={"blocks": blocks, "meta": meta,
                                                                                    **extra})]}


def _meta(state, **extra) -> dict:
    return {"intent": "master_data", "language": state["language"], "evaluated": False, "sources": [], **extra}


class MasterDataWorkflow:
    """Master-data branch of the chat graph: one method per node, added to the shared graph by `add_to()`."""

    def __init__(self, agents: dict, cfg: dict, finalize_name: str = "finalize"):
        self.agents = agents
        self.ttl = cfg.get("proposal_ttl_minutes", 30)
        self.finalize_name = finalize_name

    # ------------------------------------------------------------ 1. understand the message
    def master_parse(self, state):
        """LLM: which kind of data and what the user already typed; then match names against the DB."""
        emit("master_parse", state["language"])
        draft = state.get("master_draft") or {}
        payload = {"latest_message": state["question"], "rewritten": state["rewritten"],
                   "current_entity": draft.get("entity"), "current_values": draft.get("values")}
        out = self.agents["master_data_parser"].run(json.dumps(payload, ensure_ascii=False, default=str))
        lang = state["language"]
        if out["user_cancelled"]:
            return {"master_draft": None, "master_step": "done",
                    "draft": _text_draft(*translate_blocks([{"type": "text", "text": TEXT["cancelled"]}], lang))}
        entity = out["entity"] if out["entity"] in M.ENTITIES else draft.get("entity")
        if entity is None:                                     # belum jelas: tawarkan pilihan
            blocks = [{"type": "text", "text": TEXT["ask_entity"]}, {"type": "options", "options": ENTITY_OPTIONS}]
            return {"master_step": "done", "draft": _text_draft(*translate_blocks(blocks, lang))}
        keep = draft.get("entity") == entity and not out["is_new_request"]
        values = draft.get("values") if keep else None
        with tracing.record_tool("apply_parsed", "read", {"entity": entity, "items": out["items"]}) as run, \
                SessionLocal() as db:
            values, errors = M.apply_parsed(db, entity, values, out["fields"] or {}, out["items"] or [])
            run.done({"values": values, "errors": errors})
        return {"master_draft": {"entity": entity, "values": values, "errors": errors}, "master_step": "form"}

    # ------------------------------------------------------------ 2. show the form and wait
    def master_form(self, state):
        """Shows the form (with inline errors after a failed submit)."""
        emit("master_form", state["language"])
        draft = state["master_draft"]
        entity = draft["entity"]
        form_id = uuid.uuid4().hex
        with SessionLocal() as db:
            form = M.form_block(db, form_id, entity, draft["values"], draft.get("errors") or {})
        if draft.get("submitted") and draft.get("errors"):
            intro = TEXT["form_errors"]
        else:
            intro = TEXT["form_intro"].format(title=M.TITLE[entity].lower(), example=TYPING_EXAMPLE[entity])
        blocks = [{"type": "text", "text": intro}, form]
        return {**_reply(blocks, _meta(state, master={"form_id": form_id, "entity": entity})),
                "pending_action": {"id": form_id}}

    def master_await_form(self, state):
        """Pauses the graph until the user submits / cancels the form (or types a new message)."""
        decision = interrupt({"action_id": state["pending_action"]["id"], "kind": "form"})
        return {"master_decision": decision}

    # ------------------------------------------------------------ 3. check the submitted form
    def master_check(self, state):
        """Validates the submitted values: errors -> form again, valid -> confirmation card."""
        decision = state.get("master_decision") or {}
        kind = decision.get("decision")
        draft = state["master_draft"]
        reset = {"pending_action": None, "master_decision": None}
        if kind == "superseded":                              # pengguna mengetik: draf dipakai giliran berikutnya
            return {**reset, "final": None, "master_step": "done"}
        if kind != "submit":
            return {**reset, "master_draft": None, "master_step": "done",
                    **_reply([{"type": "text", "text": TEXT["cancelled"]}], _meta(state))}
        emit("master_check", state["language"])
        values = decision.get("values") or {}
        args = {"entity": draft["entity"], "values": values}
        with tracing.record_tool("validate_master_data", "read", args) as run, SessionLocal() as db:
            proposal, errors = M.validate(db, draft["entity"], values)
            run.done({"errors": errors} if errors else {"valid": True})
        new_draft = {**draft, "values": values, "errors": errors, "submitted": True}
        if errors:
            return {**reset, "master_draft": new_draft, "master_step": "form"}
        return {**reset, "master_draft": {**new_draft, "proposal": proposal}, "master_step": "propose"}

    # ------------------------------------------------------------ 4. confirmation card
    def master_propose(self, state):
        """Saves the proposal (`automation_actions`) and shows the confirmation card."""
        emit("master_propose", state["language"])
        p = state["master_draft"]["proposal"]
        action_id = uuid.uuid4().hex
        with SessionLocal() as db:
            db.add(AutomationAction(id=action_id, thread_id=state.get("thread_id") or "-",
                                    operation=AutomationOperation(p["operation"].upper()), status=AS.PROPOSED,
                                    proposal=p, expires_at=A.now() + timedelta(minutes=self.ttl)))
            db.commit()
        card = M.action_card(action_id, p)
        blocks = [{"type": "text", "text": TEXT["propose"]}, {"type": "action", "actionId": action_id}]
        meta = _meta(state, automation={"action_id": action_id, "operation": p["operation"], "status": "PROPOSED"})
        return {**_reply(blocks, meta, actions={action_id: card}), "pending_action": {"id": action_id}}

    def master_await(self, state):
        """Pauses the graph until the user answers the card."""
        decision = interrupt({"action_id": state["pending_action"]["id"]})
        return {"master_decision": decision}

    # ------------------------------------------------------------ 5. write to the database
    @staticmethod
    def _write(action_id: str, proposal: dict, draft: dict) -> tuple[AutomationStatus, dict, list[dict], dict | None]:
        """Creates the records in one transaction. Returns (status, result, reply blocks, draft to keep)."""
        try:
            args = {"action_id": action_id, "operation": proposal["operation"]}
            with tracing.record_tool("execute_master_data", "write", args) as run, A.write_session() as db:
                result = M.execute(db, proposal)
                run.done(result)
            return AS.EXECUTED, result, [{"type": "text", "text": M.result_text(result)}, *M.result_links(result)], None
        except AppError as e:
            reason, result = e.detail, {"error": e.detail}
        except Exception as e:  # noqa: BLE001
            log.exception("master-data action %s failed", action_id)
            reason, result = type(e).__name__, {"error": str(e)}
        keep = {k: v for k, v in draft.items() if k != "proposal"}     # pengguna bisa memperbaiki lalu kirim lagi
        return AS.FAILED, result, [{"type": "text", "text": TEXT["failed"].format(reason=reason)}], keep

    def master_execute(self, state):
        """Applies the user's decision: approve -> write; reject / expired -> mark the card."""
        decision = state.get("master_decision") or {}
        kind = decision.get("decision")
        action_id = state["pending_action"]["id"]
        reset = {"pending_action": None, "master_decision": None}
        if kind != "superseded":
            emit("master_execute", state["language"])
        with SessionLocal() as db:
            action = db.get(AutomationAction, action_id)
            expired = action.expires_at < A.now()
            if kind != "approve" or expired:
                action.status = {"reject": AS.REJECTED, "superseded": AS.SUPERSEDED}.get(kind, AS.EXPIRED)
                action.decided_at = A.now()
                db.commit()
                status = action.status
            proposal = action.proposal
        if kind == "superseded":
            return {**reset, "master_draft": None, "final": None}
        if kind != "approve" or expired:
            text = TEXT["rejected"] if status == AS.REJECTED else TEXT["expired"]
            return {**reset, "master_draft": None,
                    **_finish(state, [{"type": "text", "text": text}], action_id, UI_STATUS[status])}
        status, result, blocks, keep_draft = self._write(action_id, proposal, state["master_draft"])
        with SessionLocal() as db:
            row = db.get(AutomationAction, action_id)
            row.status, row.decided_at, row.result = status, A.now(), result
            db.commit()
        return {**reset, "master_draft": keep_draft,
                **_finish(state, blocks, action_id, UI_STATUS[status], status.value)}

    # ------------------------------------------------------------ edges & wiring
    def next_after_parse(self, state) -> str:
        return "master_form" if state["master_step"] == "form" else self.finalize_name

    @staticmethod
    def next_after_check(state) -> str:
        return {"form": "master_form", "propose": "master_propose"}.get(state["master_step"], "__end__")

    def add_to(self, g) -> None:
        """Adds the master-data nodes and edges to the chat `StateGraph`."""
        for name in ("master_parse", "master_form", "master_await_form", "master_check", "master_propose",
                     "master_await", "master_execute"):
            g.add_node(name, getattr(self, name))
        g.add_conditional_edges("master_parse", self.next_after_parse, ["master_form", self.finalize_name])
        g.add_edge("master_form", "master_await_form")
        g.add_edge("master_await_form", "master_check")
        g.add_conditional_edges("master_check", self.next_after_check, ["master_form", "master_propose", "__end__"])
        g.add_edge("master_propose", "master_await")
        g.add_edge("master_await", "master_execute")
        g.add_edge("master_execute", "__end__")


def _finish(state, blocks, action_id, ui_status, db_status=None):
    """Final reply after a card was answered (blocks + the card's new status)."""
    meta = _meta(state, automation={"action_id": action_id, "status": db_status or ui_status})
    return _reply(blocks, meta, action_updates={action_id: {"status": ui_status}})
