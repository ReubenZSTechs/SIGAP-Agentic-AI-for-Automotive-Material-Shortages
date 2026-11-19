"""Supplier Telegram agent: links, outreach dispatch, inbound routing, manager notices and timeouts.

The DB is the source of truth (conversations, messages, confirmations, change requests); the
LangGraph workflows in `configs/workflows/` hold no state between messages. Outbound messages are
always sent after the DB transaction that produced them has committed.
"""
import json
import logging
import secrets
import threading
from datetime import date, timedelta

from sqlalchemy import select

from app.chatbot.tracing import trace_scope
from app.config import settings
from app.database import SessionLocal
from app.models import (POChangeRequest, PORevision, PurchaseOrder, Supplier, SupplierConversation, SupplierMessage,
                        SupplierTelegramLink)
from app.models.enums import (ChangeRequestStatus, ConversationPurpose, ConversationStatus, MessageDirection,
                              PORevisionStatus, POStatus)
from app.supplier_chat import guardrail
from app.supplier_chat.po_pdf import pdf_file_name, render_po_pdf
from app.supplier_chat.transport import SANDBOX_MANAGER_CHAT_ID, Transport, build_transport, sandbox_chat_id
from configs.tools import po_actions as A

log = logging.getLogger(__name__)

CS, MD = ConversationStatus, MessageDirection
LANGUAGE_NAMES = {"id": "Indonesian (Bahasa Indonesia)", "en": "English"}
COMPANY = "SIGAP"

FALLBACK_OPENING = {
    "CONFIRM_ORDER": "Hello {supplier}, we have issued {po}. Please confirm that you can fulfil it and your delivery date.",
    "CANCEL_ORDER": "Hello {supplier}, we need to cancel {po}. Please confirm that this cancellation is acceptable.",
    "REVISION_CONFIRM": "Hello {supplier}, the revision of {po} you requested has been approved.",
    "WITHDRAWAL": "Hello {supplier}, we are withdrawing {po}; it no longer needs to be processed. Thank you for your cooperation.",
}
REVISION_ASK = "Are there any other changes? If not, please reply to confirm; we will then send the final PO (PDF)."
NEGOTIATION_OPENING = ("Hello {supplier}, thank you for the price information. For {po} we propose the following price; "
                       "please confirm whether it is acceptable.")
GUARD_LABEL = {"data_query": "internal data request", "sql_injection": "database query/command",
               "prompt_injection": "prompt injection", "secret_exfiltration": "request for system secrets",
               "authority_claim": "claims authority", "encoded_payload": "encoded code/payload",
               "foreign_po": "another supplier's PO"}


class SupplierChatService:
    """Owns the transport, the agents, and the supplier/manager workflows."""

    def __init__(self, agents: dict, cfg: dict, transport: Transport, manager_chat_id: int | None,
                 bot_username: str | None = None):
        from configs.workflows.manager_graph import build_manager_graph
        from configs.workflows.supplier_chat_graph import build_supplier_reply_graph
        self.agents, self.cfg, self.transport = agents, cfg, transport
        self.manager_chat_id, self.bot_username = manager_chat_id, bot_username
        self.reply_graph = build_supplier_reply_graph(self)
        self.manager_graph = build_manager_graph(self)
        self._dispatch_lock = threading.Lock()

    # ------------------------------------------ messaging ------------------------------------------
    def send(self, db, chat_id: int | None, text: str, *, direction: MessageDirection, conversation_id=None,
             supplier_id=None, buttons=None, agent_output=None, document=None) -> SupplierMessage:
        """Sends through the transport and logs the message (delivery errors are logged, not raised).

        `document={"revision_id": n}` sends the PDF of that PO version, with `text` as its caption.
        """
        rev = db.get(PORevision, document["revision_id"]) if document else None
        if rev is not None:
            if rev.pdf is None:
                rev.pdf = render_po_pdf(rev.snapshot, rev.version, final=rev.status == PORevisionStatus.FINAL,
                                        finalized_at=rev.finalized_at)
            agent_output = {**(agent_output or {}), "source": "po_pdf", "revision_id": rev.id, "po_id": rev.po_id,
                            "file_name": pdf_file_name(rev.po_number, rev.version)}
        msg = SupplierMessage(conversation_id=conversation_id, supplier_id=supplier_id, chat_id=chat_id,
                              direction=direction, text=text, buttons=buttons, agent_output=agent_output)
        if chat_id is None:
            msg.error = "chat belum terhubung / TELEGRAM_MANAGER_CHAT_ID kosong"
        else:
            try:
                if rev is not None:
                    msg.telegram_message_id = self.transport.send_document(
                        chat_id, pdf_file_name(rev.po_number, rev.version), rev.pdf, text)
                else:
                    msg.telegram_message_id = self.transport.send(chat_id, text, buttons)
            except Exception as e:  # noqa: BLE001
                log.exception("send to chat %s failed", chat_id)
                msg.error = f"{type(e).__name__}: {e}"[:300]
        db.add(msg)
        if rev is not None:
            db.flush()
            rev.pdf_message_id = msg.id
        return msg

    def deliver(self, sends: list[dict]) -> None:
        """Sends queued outbound messages (built inside a transaction) after that transaction committed."""
        if not sends:
            return
        with SessionLocal() as db:
            for s in sends:
                s = dict(s)
                self.send(db, s.pop("chat_id"), s.pop("text"), **s)
            db.commit()

    def manager_send(self, text: str, buttons=None, agent_output=None, conversation_id=None) -> dict:
        """A send dict addressed to the manager."""
        return {"chat_id": self.manager_chat_id, "text": text, "direction": MD.MANAGER_OUT, "buttons": buttons,
                "agent_output": agent_output, "conversation_id": conversation_id}

    def mirror_to_manager(self, text: str) -> int | None:
        """Shows an action taken in the Hub in the manager's Telegram chat (not logged again: the caller
        already logged it as MANAGER_IN, so the Hub's Chat Manajer does not show it twice)."""
        if self.manager_chat_id is None:
            return None
        try:
            return self.transport.send(self.manager_chat_id, text)
        except Exception:  # noqa: BLE001  (sinkronisasi tidak boleh menggagalkan keputusan)
            log.exception("mirror to manager chat failed")
            return None

    def close_manager_buttons(self, cr_id: int) -> int:
        """Removes, from the manager's Telegram messages, the option buttons of a change request that was
        decided (in Telegram, the Hub card or Chat Manajer), expired or failed. Buttons of other change
        requests that are still pending stay. Returns the number of messages edited."""
        mine = (f"cr:{cr_id}:", f"crc:{cr_id}:", f"crx:{cr_id}")
        edited = 0
        with SessionLocal() as db:
            pending = set(db.scalars(select(POChangeRequest.id).where(POChangeRequest.status.in_(
                (ChangeRequestStatus.PENDING_MANAGER, ChangeRequestStatus.AWAITING_MANAGER_CONFIRM)))))
            rows = db.scalars(select(SupplierMessage).where(SupplierMessage.direction == MD.MANAGER_OUT,
                                                            SupplierMessage.telegram_message_id.isnot(None))
                              .order_by(SupplierMessage.id.desc()).limit(200))
            for m in rows:
                buttons = m.buttons or []
                if not any(str(b.get("data", "")).startswith(mine) for b in buttons):
                    continue
                keep = [b for b in buttons if not str(b.get("data", "")).startswith(mine)
                        and button_cr_id(b.get("data")) in pending]
                try:
                    self.transport.edit_buttons(m.chat_id, m.telegram_message_id, keep or None)
                    edited += 1
                except Exception as e:  # noqa: BLE001  (pesan lama / sudah diedit: tidak kritis)
                    log.warning("edit buttons of message %s failed: %s", m.id, e)
        return edited

    def usable_chat_id(self, link: SupplierTelegramLink | None) -> int | None:
        """The link's chat id, ignoring simulated sandbox chats when running on real Telegram."""
        if link is None or link.chat_id is None:
            return None
        if self.transport.name != "sandbox" and link.chat_id == sandbox_chat_id(link.supplier_id):
            return None
        return link.chat_id

    def supplier_chat_id(self, db, supplier_id: int) -> int | None:
        return self.usable_chat_id(db.scalar(select(SupplierTelegramLink)
                                             .where(SupplierTelegramLink.supplier_id == supplier_id)))

    def run_agent(self, name: str, payload: dict, **prompt_vars) -> dict:
        prompt_vars.setdefault("language_name", LANGUAGE_NAMES["en"])
        prompt_vars.setdefault("company", COMPANY)
        prompt_vars.setdefault("today", date.today().isoformat())
        return self.agents[name].run(json.dumps(payload, ensure_ascii=False, default=str), **prompt_vars)

    # -------------------------------------------- links --------------------------------------------
    def ensure_link(self, db, supplier_id: int) -> SupplierTelegramLink:
        return ensure_link(db, supplier_id)

    def link_sandbox(self, supplier_id: int) -> SupplierTelegramLink:
        with SessionLocal() as db:
            link = self.ensure_link(db, supplier_id)
            link.chat_id, link.linked_at = sandbox_chat_id(supplier_id), A.now()
            db.commit()
            db.refresh(link)
        self.dispatch_queued()
        return link

    def _link_from_start(self, chat_id: int, text: str) -> dict:
        token = text.split(maxsplit=1)[1].strip() if len(text.split()) > 1 else ""
        with SessionLocal() as db:
            link = db.scalar(select(SupplierTelegramLink).where(SupplierTelegramLink.link_token == token)) if token else None
            if link is None:
                self.send(db, chat_id, "This link is not valid. Please ask our purchasing team for a new link.", direction=MD.OUT)
                db.commit()
                return {"handled": True, "linked": False}
            for other in db.scalars(select(SupplierTelegramLink).where(SupplierTelegramLink.chat_id == chat_id,
                                                                       SupplierTelegramLink.id != link.id)):
                other.chat_id = None                               # satu chat = satu supplier
            db.flush()
            link.chat_id, link.linked_at = chat_id, A.now()
            supplier_id = link.supplier_id
            name = db.get(Supplier, supplier_id).name
            self.send(db, chat_id, f"Connected as {name}. Purchase orders from {COMPANY} will be sent to you in this chat.",
                      direction=MD.OUT, supplier_id=supplier_id)
            db.commit()
        self.resend_failed_openings(supplier_id)
        self.dispatch_queued()
        return {"handled": True, "linked": True, "supplier_id": supplier_id}

    def resend_failed_openings(self, supplier_id: int) -> list[int]:
        """Re-sends the opening of active conversations whose messages never reached the supplier
        (e.g. the chat was linked only after dispatch, or a sandbox link was used in telegram mode)."""
        resent = []
        with SessionLocal() as db:
            chat_id = self.supplier_chat_id(db, supplier_id)
            convs = list(db.scalars(select(SupplierConversation).where(
                SupplierConversation.supplier_id == supplier_id,
                SupplierConversation.status == CS.AWAITING_SUPPLIER)))
            for conv in convs:
                outs = list(db.scalars(select(SupplierMessage).where(SupplierMessage.conversation_id == conv.id,
                                                                     SupplierMessage.direction == MD.OUT)))
                if chat_id is None or any(m.error is None for m in outs):
                    continue
                text, out = self.opening(db, conv)
                self.send(db, chat_id, text, direction=MD.OUT, conversation_id=conv.id, supplier_id=supplier_id,
                          agent_output=out)
                conv.last_activity_at = A.now()
                resent.append(conv.id)
            db.commit()
        return resent

    # ------------------------------------------- outreach -------------------------------------------
    def compose_supplier_message(self, purpose: str, snapshot: dict, *, detail: str | None = None,
                                 with_summary: bool | None = None) -> tuple[str, dict | None]:
        """LLM-written greeting/ask + exact details written by code.

        The full PO summary goes out once, with the first request for a PO (`with_summary` defaults to
        CONFIRM_ORDER only). A revision carries only `detail` (what changed); a withdrawal only the PO number.
        """
        if with_summary is None:
            with_summary = purpose == ConversationPurpose.CONFIRM_ORDER.value
        try:
            out = self.run_agent("supplier_outreach_writer", {"purpose": purpose, "supplier_name": snapshot["supplier_name"],
                                                              "po_number": snapshot["po_number"], "po": snapshot})
            body = out["message_text"]
        except Exception:  # noqa: BLE001  (pesan tetap terkirim dengan template)
            log.exception("supplier_outreach_writer failed; using template")
            out, body = None, FALLBACK_OPENING[purpose].format(supplier=snapshot["supplier_name"], po=snapshot["po_number"])
        tail = A.po_summary_text(snapshot) if with_summary else detail
        return (f"{body}\n\n{tail}" if tail else body), out

    def opening(self, db, conv: SupplierConversation) -> tuple[str, dict | None]:
        """First message of a conversation: full PO (confirm), only the changes (revision), or a
        cancellation request that repeats the PO only if the supplier never received it."""
        purpose = conv.purpose.value
        if conv.purpose == ConversationPurpose.REVISION_CONFIRM:
            cr = db.get(POChangeRequest, conv.change_request_id) if conv.change_request_id else None
            changes = ((cr.result or {}).get("applied_changes") or cr.proposed_changes) if cr else []
            diff = A.revision_diff_text(changes, cr.po_snapshot["total_amount"],
                                        conv.po_snapshot["total_amount"]) if cr else None
            if cr is not None and cr.manager_choice == "negotiate":     # harga tandingan: tanpa LLM
                diff = diff.replace("Approved changes:", "Our price proposal:")
                body = NEGOTIATION_OPENING.format(supplier=conv.po_snapshot["supplier_name"], po=conv.po_number)
                return "\n\n".join((body, diff, REVISION_ASK)), {"source": "negotiation", "change_request_id": cr.id}
            return self.compose_supplier_message(purpose, conv.po_snapshot,
                                                 detail="\n\n".join(t for t in (diff, REVISION_ASK) if t))
        if conv.purpose == ConversationPurpose.CANCEL_ORDER:
            sent_before = conv.po_id is not None and bool(A.revisions(db, conv.po_id))
            return self.compose_supplier_message(purpose, conv.po_snapshot, with_summary=not sent_before)
        return self.compose_supplier_message(purpose, conv.po_snapshot)

    def dispatch_queued(self) -> list[int]:
        """Starts queued conversations, at most one active conversation per supplier."""
        with trace_scope("supplier_outreach"):
            return self._dispatch_queued()

    def _dispatch_queued(self) -> list[int]:
        if not self._dispatch_lock.acquire(blocking=False):
            return []
        started = []
        try:
            with SessionLocal() as db:
                ids = list(db.scalars(select(SupplierConversation.id).where(SupplierConversation.status == CS.QUEUED)
                                      .order_by(SupplierConversation.id)))
            for cid in ids:
                sends = self._start_one(cid)
                if sends is not None:
                    self.deliver(sends)
                    started.append(cid)
        finally:
            self._dispatch_lock.release()
        return started

    def _start_one(self, cid: int) -> list[dict] | None:
        with SessionLocal() as db:
            conv = db.scalar(select(SupplierConversation).where(SupplierConversation.id == cid,
                                                                SupplierConversation.status == CS.QUEUED)
                             .with_for_update(skip_locked=True))
            if conv is None:
                return None
            link = db.scalar(select(SupplierTelegramLink).where(SupplierTelegramLink.supplier_id == conv.supplier_id)
                             .with_for_update())
            if self.usable_chat_id(link) is None:
                if not (conv.outcome or {}).get("not_linked_notified"):
                    conv.outcome = {**(conv.outcome or {}), "not_linked_notified": True}
                    name = db.get(Supplier, conv.supplier_id).name
                    db.commit()
                    self.deliver([self.manager_send(
                        f"Supplier {name} is not connected to Telegram yet, so {conv.po_number} "
                        f"({conv.purpose.value}) cannot be sent. Ask the supplier to open the bot link; the "
                        "conversation then starts automatically.", conversation_id=conv.id)])
                return None
            busy = db.scalar(select(SupplierConversation.id).where(
                SupplierConversation.supplier_id == conv.supplier_id, SupplierConversation.id != conv.id,
                SupplierConversation.status.in_(A.ACTIVE_CONVERSATION)))
            if busy:
                return None
            po = db.get(PurchaseOrder, conv.po_id) if conv.po_id else None
            if po is not None:                                  # data terbaru (mis. setelah revisi)
                conv.po_snapshot = A.po_snapshot(po)
            elif conv.purpose != ConversationPurpose.CANCEL_ORDER:
                A.close_conversation(conv, CS.CLOSED, reason="po_deleted_before_dispatch")
                db.commit()
                return None
            text, out = self.opening(db, conv)
            if po is not None and conv.purpose == ConversationPurpose.CONFIRM_ORDER:
                A.record_initial_revision(db, po, conv.po_snapshot)      # v1 = PO yang dikirim ke supplier
            conv.status, conv.started_at, conv.last_activity_at = CS.AWAITING_SUPPLIER, A.now(), A.now()
            chat_id, supplier_id = link.chat_id, conv.supplier_id
            db.commit()
        return [{"chat_id": chat_id, "text": text, "direction": MD.OUT, "conversation_id": cid,
                 "supplier_id": supplier_id, "agent_output": out}]

    def withdrawal_send(self, db, supplier_id: int, snapshot: dict, conversation_id: int | None) -> dict:
        text, out = self.compose_supplier_message("WITHDRAWAL", snapshot, with_summary=False)
        return {"chat_id": self.supplier_chat_id(db, supplier_id), "text": text, "direction": MD.OUT,
                "conversation_id": conversation_id, "supplier_id": supplier_id, "agent_output": out}

    # ------------------------------------------ escalation ------------------------------------------
    def escalation_send(self, situation: str, snapshot: dict, supplier_id: int, messages: list[dict],
                        conversation_id: int | None = None, detail: str | None = None) -> dict:
        """Manager notice (no options): LLM briefing + exact PO details and supplier contact."""
        with SessionLocal() as db:
            sup = db.get(Supplier, supplier_id)
            name, contact = sup.name, sup.contact
        payload = {"situation": situation, "po": snapshot, "supplier": {"name": name, "contact": contact},
                   "supplier_messages": messages[-6:], "detail": detail, "options": []}
        try:
            out = self.run_agent("manager_escalation_writer", payload)
            body = out["message_text"]
        except Exception:  # noqa: BLE001
            log.exception("manager_escalation_writer failed; using template")
            out, body = None, f"Follow-up needed ({situation}) for {snapshot['po_number']} with {name}."
        last = next((m["text"] for m in reversed(messages) if m["direction"] == MD.IN.value), None)
        extra = [A.po_summary_text(snapshot), f"Supplier: {name}" + (f" · contact: {contact}" if contact else "")]
        if last:
            extra.append(f'Last supplier message: "{last[:300]}"')
        if detail:
            extra.append(detail)
        return self.manager_send(f"{body}\n\n" + "\n".join(extra), agent_output=out, conversation_id=conversation_id)

    # -------------------------------------------- inbound --------------------------------------------
    def handle_update(self, update: dict) -> dict:
        if update.get("kind") == "message":
            return self.handle_inbound(update["chat_id"], update.get("text", ""), update.get("message_id"),
                                       attachments=update.get("attachments"))
        if update.get("kind") == "button":
            result = self.handle_button(update["chat_id"], update.get("data", ""))
            if update.get("callback_id"):
                self.transport.ack_button(update["callback_id"])
            return result
        return {"handled": False}

    def handle_button(self, chat_id: int, data: str) -> dict:
        with trace_scope("manager", button=data):
            return self._handle_button(chat_id, data)

    def _handle_button(self, chat_id: int, data: str) -> dict:
        if chat_id != self.manager_chat_id:
            return {"handled": False, "reason": "buttons are manager-only"}
        with SessionLocal() as db:
            db.add(SupplierMessage(chat_id=chat_id, direction=MD.MANAGER_IN, text=f"[tombol] {data}",
                                   agent_output={"source": "telegram", "button": data}))
            db.commit()
        return self.manager_graph.invoke({"kind": "button", "data": data}) or {}

    def handle_manager_text(self, text: str, message_id: int | None = None, author: str | None = None) -> dict:
        """Free-text manager reply, from Telegram or (with `author`) from the Hub's Chat Manajer.

        Both go through the same `manager_graph` text path; a Hub reply is also shown in Telegram so
        the two stay in sync.
        """
        with trace_scope("manager", author=author):
            return self._handle_manager_text(text, message_id, author)

    def _handle_manager_text(self, text: str, message_id: int | None, author: str | None) -> dict:
        mirrored = self.mirror_to_manager(f"💬 {author} via Hub: {text}") if author else None
        with SessionLocal() as db:
            db.add(SupplierMessage(chat_id=self.manager_chat_id, direction=MD.MANAGER_IN, text=text,
                                   telegram_message_id=message_id if author is None else mirrored,
                                   agent_output={"source": "hub", "author": author} if author else {"source": "telegram"}))
            db.commit()
        return self.manager_graph.invoke({"kind": "text", "text": text}) or {}

    def handle_inbound(self, chat_id: int, text: str, message_id: int | None = None,
                       attachments: list[dict] | None = None) -> dict:
        manager = self.manager_chat_id is not None and chat_id == self.manager_chat_id
        with trace_scope("manager" if manager else "supplier", chat_id=None if manager else chat_id):
            return self._handle_inbound(chat_id, text, message_id, attachments)

    def _handle_inbound(self, chat_id: int, text: str, message_id: int | None = None,
                        attachments: list[dict] | None = None) -> dict:
        text = (text or "").strip()
        if attachments and chat_id != self.manager_chat_id:      # foto/PDF supplier -> Agent Hub (dokumen)
            from app.hub import hooks as hub_hooks
            stored = hub_hooks.store_attachments(self, chat_id, text, attachments, message_id)
            if stored is not None:
                return stored
        if not text:
            return {"handled": False}
        if self.manager_chat_id is not None and chat_id == self.manager_chat_id:
            if text.startswith("/start") and len(text.split()) > 1:
                self.deliver([self.manager_send(
                    "This chat is registered as the MANAGER (TELEGRAM_MANAGER_CHAT_ID), so it cannot be linked "
                    "as a supplier. Open the supplier link from another Telegram account, or use a Telegram group "
                    "as the manager chat.")])
                return {"handled": True, "linked": False, "reason": "manager_chat"}
            return self.handle_manager_text(text, message_id)
        if text.startswith("/start"):
            return self._link_from_start(chat_id, text)
        with SessionLocal() as db:
            link = db.scalar(select(SupplierTelegramLink).where(SupplierTelegramLink.chat_id == chat_id))
            if link is None:
                log.info("ignoring message from unknown chat %s", chat_id)
                return {"handled": False, "reason": "unknown_chat"}
            conv = db.scalar(select(SupplierConversation).where(
                SupplierConversation.supplier_id == link.supplier_id,
                SupplierConversation.status.in_(A.ACTIVE_CONVERSATION)).order_by(SupplierConversation.id))
            msg = SupplierMessage(conversation_id=conv.id if conv else None, supplier_id=link.supplier_id,
                                  chat_id=chat_id, direction=MD.IN, text=text, telegram_message_id=message_id)
            db.add(msg)
            if conv is not None:
                conv.last_activity_at = A.now()
            db.commit()
            supplier_id, msg_id = link.supplier_id, msg.id
            conv_id, conv_status, po_number = (conv.id, conv.status, conv.po_number) if conv else (None, None, None)
        with trace_scope("supplier", supplier_id=supplier_id, conversation_id=conv_id):
            return self._route_supplier_message(chat_id, text, supplier_id, msg_id, conv_id, conv_status, po_number)

    def _route_supplier_message(self, chat_id, text, supplier_id, msg_id, conv_id, conv_status, po_number) -> dict:
        from app.hub import hooks as hub_hooks
        if hub_hooks.is_human_mode(supplier_id):                # admin mengambil alih di Agent Hub: tidak dibalas agent
            return {"handled": True, "human_mode": True, "conversation_id": conv_id}
        with SessionLocal() as db:                               # guardrail: sebelum pesan sampai ke LLM mana pun
            verdict = guardrail.check_inbound(text, guardrail.own_po_numbers(db, supplier_id))
        if verdict is not None:
            return self.guard_block(verdict, supplier_id, chat_id, text, msg_id, conv_id)
        if conv_id is None:
            routed = hub_hooks.route_mission_reply(self, supplier_id, chat_id, text, msg_id)   # misi Hub yang menunggu
            if routed is not None:
                return routed
            return self._triage(supplier_id, chat_id, text, msg_id)
        if conv_status == CS.REVISION_REQUESTED:
            self.deliver([{"chat_id": chat_id, "conversation_id": conv_id, "supplier_id": supplier_id, "direction": MD.OUT,
                           "text": f"Thank you. Your change request for {po_number} is being reviewed by our "
                                   "manager; we will get back to you shortly."}])
            return {"handled": True, "conversation_id": conv_id, "waiting_for": "manager"}
        return self.reply_graph.invoke({"conversation_id": conv_id, "text": text}) or {}

    # ------------------------------------------ guardrail ------------------------------------------
    def guard_block(self, verdict, supplier_id: int, chat_id: int, text: str, msg_id: int | None,
                    conv_id: int | None = None) -> dict:
        """Fixed refusal (written by code) + audit; the manager is alerted on attack attempts (max 1/hour/supplier)."""
        from app.hub.audit_log import agent as audit_agent
        from app.models import HubAuditLog
        reply = verdict.reply(text)
        alert = None
        with SessionLocal() as db:
            sup = db.get(Supplier, supplier_id)
            if msg_id:
                msg = db.get(SupplierMessage, msg_id)
                msg.agent_output = {**(msg.agent_output or {}), "guardrail": verdict.as_dict()}
            if verdict.alert:
                recent = db.scalar(select(HubAuditLog.id).where(
                    HubAuditLog.action == "guardrail_alert", HubAuditLog.supplier_id == supplier_id,
                    HubAuditLog.at >= A.now() - timedelta(hours=1)).limit(1))
                if recent is None:
                    alert = (f"⚠️ Guardrail: a message from {sup.name} was blocked ({GUARD_LABEL.get(verdict.category, verdict.category)}). "
                             f'The agent replied with a standard refusal; no data was shared.\nMessage: "{text[:300]}"')
                    audit_agent(db, "guardrail_alert", "supplier", supplier_id, f"Manajer diberi tahu: {verdict.category}",
                                supplier_id=supplier_id)
            audit_agent(db, "guardrail_block", "supplier", supplier_id,
                        f"Pesan {sup.name} ditolak guardrail ({GUARD_LABEL.get(verdict.category, verdict.category)})",
                        supplier_id=supplier_id, **verdict.as_dict(), message=text[:300])
            db.commit()
        sends = [{"chat_id": chat_id, "text": reply, "direction": MD.OUT, "supplier_id": supplier_id,
                  "conversation_id": conv_id, "agent_output": {"source": "guardrail", **verdict.as_dict()}}]
        if alert:
            sends.append(self.manager_send(alert, agent_output={"source": "guardrail", **verdict.as_dict()}))
        self.deliver(sends)
        return {"handled": True, "guardrail": verdict.as_dict(), "conversation_id": conv_id}

    def safe_text(self, supplier_id: int, text: str, supplier_text: str = "") -> tuple[str, str | None]:
        """LLM-written reply checked for leaks before it reaches the supplier (see guardrail.check_outbound)."""
        with SessionLocal() as db:
            return guardrail.safe_reply(db, supplier_id, text, supplier_text)

    def _triage(self, supplier_id: int, chat_id: int, text: str, msg_id: int) -> dict:
        """A linked supplier writes while no conversation is open (e.g. a date change or cancellation after confirming)."""
        with SessionLocal() as db:
            pos = list(db.scalars(select(PurchaseOrder).where(
                PurchaseOrder.supplier_id == supplier_id,
                PurchaseOrder.status.in_((POStatus.ISSUED, POStatus.PARTIALLY_RECEIVED))).order_by(PurchaseOrder.id)))
            open_pos = []
            for po in pos:
                conf = A.confirmation(db, po.id)
                open_pos.append({**A.po_snapshot(po), "confirmation_status": conf.status.value,
                                 "promised_delivery_date": A._iso(conf.promised_delivery_date)})
            db.commit()
            recent = [{"direction": m.direction.value, "text": m.text} for m in db.scalars(
                select(SupplierMessage).where(SupplierMessage.supplier_id == supplier_id)
                .order_by(SupplierMessage.id.desc()).limit(6))][::-1]
        out = self.run_agent("supplier_inbound_triage", {"supplier_message": text, "open_pos": open_pos,
                                                         "recent_messages": recent})
        po = next((p for p in open_pos if p["po_number"] == out.get("po_number")), None)
        intent, promised = out["intent"], A.valid_future_date(out.get("promised_delivery_date"))
        if intent == "data_request":                              # lapisan kedua guardrail (klasifikasi LLM)
            return self.guard_block(guardrail.from_llm("data_request", "llm_triage"), supplier_id, chat_id, text, msg_id)
        if intent == "cancellation_request" and po is not None:
            return self._supplier_cancellation(supplier_id, chat_id, po, out.get("reason") or text[:200], text, out)
        confirmed = po is not None and po["confirmation_status"] == "CONFIRMED"
        if confirmed and promised and intent in ("delivery_change", "confirmation", "acknowledgement"):
            return self._record_delivery_update(supplier_id, chat_id, po, promised, out, text)
        if confirmed and intent == "delivery_change":            # tanggal tidak jelas: tanya tanggal pasti
            self.deliver([{"chat_id": chat_id, "supplier_id": supplier_id, "direction": MD.OUT, "agent_output": out,
                           "text": f"Thank you for the information. Please state the exact delivery date for "
                                   f"{po['po_number']} (for example: 28 October) so we can process it."}])
            return {"handled": True, "triage": out, "asked_for_date": po["po_number"]}
        if confirmed and intent in ("confirmation", "acknowledgement"):   # sudah final: tanpa percakapan / PDF baru
            self.deliver([{"chat_id": chat_id, "supplier_id": supplier_id, "direction": MD.OUT, "agent_output": out,
                           "text": f"Thank you, {po['po_number']} is already recorded as confirmed."}])
            return {"handled": True, "triage": out, "acknowledged": po["po_number"]}
        if po is not None and intent in ("revision_request", "confirmation", "delivery_change", "acknowledgement"):
            with A.write_session() as db:
                conv = A.queue_conversation(db, db.get(PurchaseOrder, po["id"]), ConversationPurpose.CONFIRM_ORDER)
                conv.status, conv.started_at, conv.last_activity_at = CS.AWAITING_SUPPLIER, A.now(), A.now()
                conv.outcome = {"opened_by": "supplier_message", "triage": out,
                                **({"collected": {"promised_delivery_date": promised}} if promised else {})}
                db.get(SupplierMessage, msg_id).conversation_id = conv.id
                db.flush()
                cid = conv.id
            return self.reply_graph.invoke({"conversation_id": cid, "text": text}) or {}
        reply, blocked = self.safe_text(supplier_id, out["reply_text"], text)
        if po is None and open_pos and out["intent"] in ("revision_request", "cancellation_request", "delivery_change"):
            reply += "\nYour open POs: " + ", ".join(p["po_number"] for p in open_pos)
        self.deliver([{"chat_id": chat_id, "text": reply, "direction": MD.OUT, "supplier_id": supplier_id,
                       "agent_output": {**out, **({"guardrail_output": blocked} if blocked else {})}}])
        return {"handled": True, "triage": out}

    def _record_delivery_update(self, supplier_id: int, chat_id: int, po: dict, promised: str, out: dict,
                                text: str = "") -> dict:
        """New delivery date for an already confirmed PO.

        Within the agent's early/late window (Hub policy): the PO gets a new FINAL version with the date and
        the supplier and manager are told. Outside: a DATE_CHANGE request with options for the manager.
        """
        from app.hub.audit_log import agent as audit_agent
        with A.write_session() as db:
            row = db.get(PurchaseOrder, po["id"])
            res = A.apply_delivery_date(db, row, promised, text or out.get("reply_text", ""))
            check = res["check"]
            if res["auto"]:
                audit_agent(db, "auto_accept_date", "po", row.id,
                            f"Tanggal kirim {row.po_number} diterima agent: {check.describe()} (versi {res['version']})",
                            supplier_id=supplier_id, po_number=row.po_number, new_date=promised)
            else:
                audit_agent(db, "escalate_date", "change_request", res["change_request_id"],
                            f"Tanggal kirim {row.po_number} di luar batas agent: {check.describe()}; menunggu manajer",
                            supplier_id=supplier_id, po_number=row.po_number, new_date=promised)
            name = row.supplier_name
        if res["auto"]:
            self.deliver([
                {"chat_id": chat_id, "supplier_id": supplier_id, "direction": MD.OUT, "agent_output": out,
                 "text": f"Thank you. We have updated the delivery date of {po['po_number']} to {promised}. "
                         f"Attached is PO version {res['version']} for your reference.",
                 "document": {"revision_id": res["revision_id"]}},
                self.manager_send(f"ℹ️ {name} changed the delivery date of {po['po_number']} to {promised}. "
                                  f"It is within the agent's limits ({check.describe()}), so the agent accepted it and "
                                  f"revised the PO to version {res['version']}.")])
            return {"handled": True, "triage": out, "promised_delivery_date": promised, "auto_accepted": True}
        self.deliver([{"chat_id": chat_id, "supplier_id": supplier_id, "direction": MD.OUT, "agent_output": out,
                       "text": f"Thank you. We are checking the new delivery date {promised} for {po['po_number']} "
                               "with our manager and will get back to you shortly."}])
        presented = self.manager_graph.invoke({"kind": "present", "change_request_id": res["change_request_id"]})
        self.deliver(presented.get("sends", []))
        return {"handled": True, "triage": out, "promised_delivery_date": promised,
                "change_request_id": res["change_request_id"]}

    def _supplier_cancellation(self, supplier_id: int, chat_id: int, po: dict, reason: str, text: str,
                               out: dict | None = None, conversation_id: int | None = None) -> dict:
        """The supplier cancels an issued PO: cancelled automatically, the manager is told, and a replacement is
        ordered within the agent's limits (late / off-band / none -> the manager decides)."""
        from app.hub.audit_log import agent as audit_agent
        with A.write_session() as db:
            row = db.get(PurchaseOrder, po["id"])
            res = A.handle_supplier_cancellation(db, row, reason, text)
            if res["status"] == "partial":
                audit_agent(db, "supplier_cancel_partial", "po", row.id,
                            f"{row.supplier_name} cancelled {row.po_number} after a partial receipt; sent to the manager",
                            supplier_id=supplier_id, po_number=row.po_number, reason=reason)
            else:
                audit_agent(db, "supplier_cancelled", "po", row.id,
                            f"{row.po_number} cancelled automatically at the supplier's request: {reason}",
                            supplier_id=supplier_id, po_number=row.po_number, reason=reason)
                self._audit_resourcing(db, audit_agent, row, res, supplier_id)
            snap, name = A.po_snapshot(row), row.supplier_name
        if res["status"] == "partial":
            self.deliver([{"chat_id": chat_id, "supplier_id": supplier_id, "direction": MD.OUT, "agent_output": out,
                           "conversation_id": conversation_id,
                           "text": f"Thank you for letting us know. Because part of {po['po_number']} has already been "
                                   "received, our purchasing team will contact you about the remaining quantity."},
                          self.escalation_send("supplier_cancel_partial", snap, supplier_id,
                                               [{"direction": MD.IN.value, "text": text}], conversation_id,
                                               f"Supplier's reason: {reason}")])
            return {"handled": True, "cancellation": "partial", "po_number": po["po_number"]}
        supplier_text = (f"Understood, we accept the cancellation of {po['po_number']} and the PO has been cancelled. "
                         "Thank you for letting us know.")
        intro = f"ℹ️ {name} cancelled {po['po_number']} ({reason}). The PO was cancelled automatically."
        return {"cancellation": res["status"], **self._after_cancel(res, supplier_id, chat_id, supplier_text, intro,
                                                                    out, conversation_id)}

    def _price_cancellation(self, supplier_id: int, chat_id: int, po: dict, prices: list[dict], text: str,
                            out: dict | None = None, conversation_id: int | None = None) -> dict:
        """The supplier asks a price so far off (beyond ±price_cancel_pct, or <= 0) that the agent cancels the PO
        itself, informs supplier and manager, and re-sources the material (no human approval needed)."""
        from app.hub.audit_log import agent as audit_agent
        with A.write_session() as db:
            row = db.get(PurchaseOrder, po["id"])
            res = A.cancel_for_unreasonable_price(db, row, prices, text)
            if res is None:                                   # guarded by the graph (PO must be cancellable)
                raise RuntimeError(f"{row.po_number} cannot be cancelled automatically")
            audit_agent(db, "auto_cancel_price", "po", row.id,
                        f"{row.po_number} cancelled by the agent: {res['reason']}"[:300],
                        supplier_id=supplier_id, po_number=row.po_number, prices=prices)
            self._audit_resourcing(db, audit_agent, row, res, supplier_id)
            name = row.supplier_name
        change = "; ".join(f"{p['sku']} {A.rupiah(p['old'])} → {A.rupiah(p['new'])} ({p['pct']:+.1f}%)" for p in prices)
        supplier_text = (f"Thank you. We cannot accept the requested price change for {po['po_number']} ({change}); "
                         "it is far outside the agreed price, so we have cancelled this PO.")
        intro = (f"⚠️ {name} asked an unreasonable price for {po['po_number']}: {change} (beyond the "
                 f"±{prices[0]['cancel_at']:g}% auto-cancel limit). The agent cancelled the PO without approval.")
        return {"price_cancel": res["status"], **self._after_cancel(res, supplier_id, chat_id, supplier_text, intro,
                                                                    out, conversation_id)}

    @staticmethod
    def _audit_resourcing(db, audit_agent, row, res: dict, supplier_id: int) -> None:
        for np in res["new_pos"]:
            audit_agent(db, "replacement_po", "po", np["id"],
                        f"Agent issued {np['po_number']} to {np['supplier_name']} as a replacement for {row.po_number} "
                        f"({A.rupiah(np['total_amount'])}, lead time {np['lead_time_days']} days)",
                        supplier_id=None, po_number=np["po_number"], replaces=row.po_number)
        if res["change_request_id"]:
            audit_agent(db, "escalate_cancellation", "change_request", res["change_request_id"],
                        f"Replacement for {row.po_number} needs a manager decision: "
                        + ("; ".join(res["warnings"]) or "no other supplier"),
                        supplier_id=supplier_id, po_number=row.po_number)

    def _after_cancel(self, res: dict, supplier_id: int, chat_id: int, supplier_text: str, manager_intro: str,
                      out: dict | None, conversation_id: int | None) -> dict:
        """Tell the supplier, then either report the replacement PO(s) or present the manager's options."""
        sends = [{"chat_id": chat_id, "supplier_id": supplier_id, "direction": MD.OUT, "agent_output": out,
                  "conversation_id": conversation_id, "text": supplier_text}]
        if res["status"] == "replaced":
            sends.append(self.manager_send(
                f"{manager_intro} The agent issued "
                + "; ".join(f"{p['po_number']} to {p['supplier_name']} ({A.rupiah(p['total_amount'])}, lead time "
                            f"{p['lead_time_days']} days)" for p in res["new_pos"])
                + " and is contacting the new supplier (track it in Supplier Hub → Missions). Price and delivery "
                  "are within the agent's limits."))
            self.deliver(sends)
            self.dispatch_queued()
            return {"handled": True, "new_pos": res["new_pos"]}
        sends.append(self.manager_send(f"{manager_intro} No replacement within the agent's limits; please decide below."))
        self.deliver(sends)
        presented = self.manager_graph.invoke({"kind": "present", "change_request_id": res["change_request_id"]})
        self.deliver(presented.get("sends", []))
        return {"handled": True, "change_request_id": res["change_request_id"]}

    # ------------------------------------------- timeouts -------------------------------------------
    def tick_timeouts(self) -> dict:
        """Reminders, no-response escalation, and expiry of change requests the manager ignored."""
        with trace_scope("supplier_outreach"):
            return self._tick_timeouts()

    def _tick_timeouts(self) -> dict:
        now = A.now()
        remind_at = now - timedelta(hours=self.cfg.get("reminder_after_hours", 24))
        escalate_at = now - timedelta(hours=self.cfg.get("escalate_after_hours", 72))
        expire_at = now - timedelta(hours=self.cfg.get("change_request_ttl_hours", 48))
        sends, escalations, expired, counts = [], [], [], {"reminded": 0, "escalated": 0, "expired": 0}
        with SessionLocal() as db:
            for conv in db.scalars(select(SupplierConversation).where(SupplierConversation.status == CS.AWAITING_SUPPLIER)):
                last = conv.last_activity_at or conv.started_at or conv.created_at
                if last < escalate_at:
                    A.close_conversation(conv, CS.ESCALATED, reason="no_response")
                    escalations.append(("no_response", conv.po_snapshot, conv.supplier_id, conv.id))
                    counts["escalated"] += 1
                elif last < remind_at and conv.reminded_at is None:
                    conv.reminded_at = now
                    sends.append({"chat_id": self.supplier_chat_id(db, conv.supplier_id), "direction": MD.OUT,
                                  "conversation_id": conv.id, "supplier_id": conv.supplier_id,
                                  "text": f"Reminder: please reply about {conv.po_number} "
                                          "(the details are in our previous message)."})
                    counts["reminded"] += 1
            for cr in db.scalars(select(POChangeRequest).where(
                    POChangeRequest.status.in_((ChangeRequestStatus.PENDING_MANAGER,
                                                ChangeRequestStatus.AWAITING_MANAGER_CONFIRM)),
                    POChangeRequest.created_at < expire_at)):
                cr.status = ChangeRequestStatus.EXPIRED
                expired.append(cr.id)
                conv = db.get(SupplierConversation, cr.conversation_id) if cr.conversation_id else None
                if conv is not None and conv.status == CS.REVISION_REQUESTED:
                    A.close_conversation(conv, CS.ESCALATED, reason="change_request_expired")
                sends.append(self.manager_send(f"Request #{cr.id} for {cr.po_number} expired without a decision. "
                                               "Contact the supplier directly if it is still needed."))
                counts["expired"] += 1
            db.commit()
        self.deliver(sends)
        for cr_id in expired:
            self.close_manager_buttons(cr_id)
        for situation, snap, supplier_id, cid in escalations:
            self.deliver([self.escalation_send(situation, snap, supplier_id, self.messages(cid), cid)])
        return counts

    def messages(self, conversation_id: int, limit: int | None = None) -> list[dict]:
        limit = limit or self.cfg.get("history_messages", 12)
        with SessionLocal() as db:
            rows = db.scalars(select(SupplierMessage).where(SupplierMessage.conversation_id == conversation_id)
                              .order_by(SupplierMessage.id.desc()).limit(limit))
            return [{"direction": m.direction.value, "text": m.text} for m in rows][::-1]


def button_cr_id(data) -> int | None:
    """Change request id of a manager button (`cr:<id>:<choice>`, `crc:<id>:<choice>`, `crx:<id>`)."""
    parts = str(data or "").split(":")
    if len(parts) >= 2 and parts[0] in ("cr", "crc", "crx") and parts[1].isdigit():
        return int(parts[1])
    return None


def ensure_link(db, supplier_id: int) -> SupplierTelegramLink:
    """Link row with a random /start token (created on first use)."""
    link = db.scalar(select(SupplierTelegramLink).where(SupplierTelegramLink.supplier_id == supplier_id))
    if link is None:
        link = SupplierTelegramLink(supplier_id=supplier_id, link_token=secrets.token_urlsafe(18))
        db.add(link)
        db.flush()
    return link


def deep_link(link: SupplierTelegramLink) -> str | None:
    """t.me deep link that links the supplier's chat when opened (needs TELEGRAM_BOT_USERNAME)."""
    username = settings.TELEGRAM_BOT_USERNAME
    return f"https://t.me/{username}?start={link.link_token}" if username else None


_lock = threading.Lock()
_service: SupplierChatService | None = None


def manager_chat_id() -> int | None:
    if settings.TELEGRAM_MANAGER_CHAT_ID is not None:
        return settings.TELEGRAM_MANAGER_CHAT_ID
    return SANDBOX_MANAGER_CHAT_ID if settings.TELEGRAM_MODE == "sandbox" else None


def get_supplier_chat_service() -> SupplierChatService:
    """Lazily builds the production service (raises `ChatUnavailable` without SAP AI Core credentials)."""
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                from app.chatbot.service import live_agents
                agents, registry = live_agents()
                _service = SupplierChatService(agents, registry.supplier_chat, build_transport(settings),
                                               manager_chat_id(), settings.TELEGRAM_BOT_USERNAME)
    return _service


def dispatch_in_background() -> None:
    """Fire-and-forget dispatch (used after the Dashboard automation queued conversations)."""
    def run():
        try:
            get_supplier_chat_service().dispatch_queued()
        except Exception:  # noqa: BLE001  (worker akan mencoba lagi)
            log.exception("background dispatch failed")
    threading.Thread(target=run, name="supplier-dispatch", daemon=True).start()
