"""PO automation branch of the chat graph (CRUD on purchase orders only).

    auto_parse -> auto_resolve -+- needs input -> auto_clarify -> finalize (wait for the user's answer)
                                +- refused     -> finalize (explain)
                                +- resolved    -> auto_propose -> auto_await (interrupt) -> auto_execute

The proposal and the result message are built from DB values only; the confirmation is a
LangGraph `interrupt()`, persisted by the checkpointer and resumed by `ChatService.stream(resume=...)`.
"""
import json
import logging
import uuid
from datetime import date, timedelta

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from app.chatbot.progress import emit
from app.core.exceptions import AppError
from app.database import SessionLocal
from app.models import AutomationAction
from app.models.enums import AutomationOperation, AutomationStatus, ConversationPurpose
from configs.tools import po_actions as A

log = logging.getLogger(__name__)
AS = AutomationStatus

TEXT = {
    "id": {
        "refused": "Permintaan ini tidak dapat dijalankan: {reason}",
        "gave_up": "Maaf, detail permintaan PO belum lengkap setelah beberapa kali klarifikasi. Silakan ulangi "
                   "permintaan dengan lengkap (material, jumlah, dan supplier bila ada) atau gunakan halaman Manual PO.",
        "cancelled": "Baik, permintaan PO dibatalkan. Tidak ada data yang diubah.",
        "rejected": "Baik, usulan tidak dijalankan. Tidak ada data yang diubah.",
        "expired": "Usulan ini sudah kedaluwarsa. Silakan kirim ulang permintaannya.",
        "failed": "Perubahan gagal dijalankan: {reason}",
        "create": "{po} dibuat dan diterbitkan (ISSUED) ke {supplier}, total {total}.",
        "create_tail": "Agent akan menghubungi supplier via Telegram untuk konfirmasi pesanan.",
        "update": "{po} diperbarui. Total {before} → {after}.",
        "delete_now": "{po} dihapus. Stok on-order dan planning disesuaikan.",
        "delete_supplier": "Permintaan pembatalan {po} dikirim ke {supplier} via Telegram. PO akan dihapus setelah "
                           "supplier menyetujui; bila supplier menolak, manajer akan diberi tahu.",
        "propose_create": "Saya siapkan PO berikut. Periksa lalu konfirmasi:",
        "propose_update": "Saya siapkan perubahan {po} berikut. Periksa lalu konfirmasi:",
        "propose_delete_now": "{po} ({status}) belum dikirim ke supplier, jadi akan langsung dihapus. Konfirmasi?",
        "propose_delete_supplier": "{po} sudah diterbitkan ke {supplier}. Saya akan meminta persetujuan pembatalan "
                                   "via Telegram dan menghapusnya setelah supplier setuju. Konfirmasi?",
    },
    "en": {
        "refused": "This request cannot be carried out: {reason}",
        "gave_up": "Sorry, the PO request is still incomplete after several clarifications. Please send it again with "
                   "all details (material, quantity, and supplier if any) or use the Manual PO page.",
        "cancelled": "OK, the PO request was cancelled. Nothing was changed.",
        "rejected": "OK, the proposal was not executed. Nothing was changed.",
        "expired": "This proposal has expired. Please send the request again.",
        "failed": "The change failed: {reason}",
        "create": "{po} was created and issued (ISSUED) to {supplier}, total {total}.",
        "create_tail": "The agent will contact the supplier on Telegram to confirm the order.",
        "update": "{po} was updated. Total {before} → {after}.",
        "delete_now": "{po} was deleted. On-order stock and planning were adjusted.",
        "delete_supplier": "A cancellation request for {po} was sent to {supplier} on Telegram. The PO is deleted once "
                           "the supplier agrees; if they refuse, the manager is notified.",
        "propose_create": "I prepared the following PO. Please review and confirm:",
        "propose_update": "I prepared these changes to {po}. Please review and confirm:",
        "propose_delete_now": "{po} ({status}) was never sent to the supplier, so it will be deleted right away. Confirm?",
        "propose_delete_supplier": "{po} was already issued to {supplier}. I will ask them on Telegram to agree to the "
                                   "cancellation and delete it once they do. Confirm?",
    },
}


def _t(lang: str, key: str, **kw) -> str:
    return TEXT.get(lang, TEXT["id"])[key].format(**kw)


def _text_draft(*texts: str) -> dict:
    return {"blocks": [{"type": "text", "text": t} for t in texts if t], "claims": [], "insufficient_data": False}


def _table(title: str, columns: list[str], rows: list[list]) -> dict:
    return {"type": "table", "title": title, "columns": columns, "rows": rows}


def proposal_tables(p: dict) -> list[dict]:
    """Rendered tables of a proposal (shown in the chat and inside the action card)."""
    cols = ["SKU", "Material", "Qty", "Harga", "Subtotal", "Dibutuhkan"]

    def rows(items):
        return [[i["sku"], i["name"], f"{A.fmt_qty(i['qty_ordered'])} {i.get('uom', '')}".strip(), A.rupiah(i["unit_price"]),
                 A.rupiah(i["line_total"]), i.get("needed_by_date") or "–"] for i in items]

    if p["operation"] == "create":
        return [_table(f"{g['supplier_code']} {g['supplier_name']} · Net {g['payment_term_days']} · total "
                       f"{A.rupiah(g['total_amount'])}", cols, rows(g["items"])) for g in p["purchase_orders"]]
    if p["operation"] == "update":
        return [_table(f"{p['po']['po_number']} setelah perubahan · total {A.rupiah(p['total_before'])} → "
                       f"{A.rupiah(p['total_after'])}", cols, rows(p["items_after"]))]
    return [_table(f"{p['po']['po_number']} · {p['po']['supplier_name']} · {p['po']['status']} · total "
                   f"{A.rupiah(p['po']['total_amount'])}", cols, rows(p["po"]["items"]))]


def action_card(action_id: str, p: dict, status: str = "pending") -> dict:
    op = p["operation"]
    if op == "create":
        title = "Buat & terbitkan PO" + (f" ({len(p['purchase_orders'])} supplier)" if len(p["purchase_orders"]) > 1 else "")
        detail = f"Total {A.rupiah(p['grand_total'])}. Supplier dihubungi via Telegram setelah dikonfirmasi."
        approve = "Konfirmasi & terbitkan"
    elif op == "update":
        title, approve = f"Ubah {p['po']['po_number']}", "Konfirmasi perubahan"
        detail = f"Total {A.rupiah(p['total_before'])} → {A.rupiah(p['total_after'])}."
    else:
        title, approve = f"Hapus {p['po']['po_number']}", "Konfirmasi hapus"
        detail = ("Langsung dihapus (belum dikirim ke supplier)." if p["mode"] == "immediate"
                  else "Minta persetujuan pembatalan ke supplier via Telegram, lalu hapus.")
    return {"id": action_id, "kind": op, "title": title, "detail": detail, "approveLabel": approve,
            "status": status, "tables": proposal_tables(p), "warnings": p.get("warnings") or []}


UI_STATUS = {AS.PROPOSED: "pending", AS.EXECUTED: "approved", AS.AWAITING_SUPPLIER: "approved",
             AS.REJECTED: "rejected", AS.SUPERSEDED: "expired", AS.EXPIRED: "expired", AS.FAILED: "failed"}


def add_automation_nodes(g, agents: dict, cfg: dict, finalize_name: str = "finalize", on_supplier_work=None) -> None:
    """Adds the automation nodes/edges to the chat `StateGraph` (shared `ChatState`)."""
    ttl = cfg.get("proposal_ttl_minutes", 30)
    max_rounds = cfg.get("max_clarify_rounds", 3)
    actor = cfg.get("actor", "Agent MRP (dikonfirmasi pengguna)")
    from configs.workflows.chat_graph import LANGUAGE_NAMES

    def auto_parse(state):
        emit("auto_parse", state["language"])
        pending = state.get("automation_draft") or {}
        payload = {"latest_message": state["question"], "rewritten": state["rewritten"],
                   "current_draft": pending.get("request"), "last_clarification": pending.get("last_clarification")}
        out = agents["automation_parser"].run(json.dumps(payload, ensure_ascii=False), today=date.today().isoformat())
        rounds = pending.get("rounds", 0)
        if out["user_cancelled"] or out["operation"] == "none" and pending:
            return {"automation_draft": None, "draft": _text_draft(_t(state["language"], "cancelled")),
                    "automation_step": "done"}
        request = {k: out[k] for k in ("operation", "po_reference", "items", "supplier_query", "needed_by_date", "notes")}
        if out["is_new_request"]:
            rounds = 0                                         # permintaan baru: hitungan klarifikasi mulai lagi
        else:
            request = _drop_stale_supplier(request, pending.get("request"))
        return {"automation_draft": {"request": request, "rounds": rounds, "last_clarification": None},
                "automation_step": "resolve"}

    def _drop_stale_supplier(request: dict, previous: dict | None) -> dict:
        """Safety net if the parser merged a new request into the old draft: a supplier carried over from
        a draft about other materials does not apply (the user can still name one again)."""
        old_sup = (previous or {}).get("supplier_query")
        if not old_sup or request.get("supplier_query") != old_sup or not request.get("items") \
                or not previous.get("items"):
            return request
        with SessionLocal() as db:
            now_ids, then_ids = A.material_ids(db, request["items"]), A.material_ids(db, previous["items"])
        if now_ids and then_ids and not now_ids & then_ids:
            return {**request, "supplier_query": None}
        return request

    def auto_resolve(state):
        emit("auto_resolve", state["language"])
        draft = state["automation_draft"]
        with SessionLocal() as db:
            res = A.resolve_po_request(db, draft["request"])
        return {"automation_resolution": res, "automation_step": res["status"]}

    def auto_clarify(state):
        lang = state["language"]
        emit("auto_clarify", lang)
        draft, res = state["automation_draft"], state["automation_resolution"]
        if res["status"] == "refused":
            return {"automation_draft": None, "draft": _text_draft(_t(lang, "refused", reason=res["refusal"]))}
        if draft["rounds"] >= max_rounds:
            return {"automation_draft": None, "draft": _text_draft(_t(lang, "gave_up"))}
        allowed = {o["value"]: o for a in res["ambiguous"] for o in a["options"]}
        out = agents["automation_clarifier"].run(
            json.dumps({"operation": res["operation"], "request": draft["request"], "missing": res["missing"],
                        "ambiguous": res["ambiguous"], "errors": res["errors"]}, ensure_ascii=False),
            language_name=LANGUAGE_NAMES[lang])
        options = [allowed[o["value"]] for o in out["options"] if o["value"] in allowed][:A.MAX_OPTIONS]
        if not options and res["ambiguous"]:
            options = res["ambiguous"][0]["options"][:A.MAX_OPTIONS]
        blocks = [{"type": "text", "text": out["question_text"]}]
        if options:
            blocks.append({"type": "options", "options": options})
        new_draft = {**draft, "rounds": draft["rounds"] + 1,
                     "last_clarification": {"question": out["question_text"], "options": options}}
        return {"automation_draft": new_draft, "draft": {"blocks": blocks, "claims": [], "insufficient_data": False}}

    def auto_propose(state):
        lang = state["language"]
        emit("auto_propose", lang)
        p = state["automation_resolution"]["proposal"]
        action_id = uuid.uuid4().hex
        po = p.get("po") or {}
        with SessionLocal() as db:
            db.add(AutomationAction(id=action_id, thread_id=state.get("thread_id") or "-",
                                    operation=AutomationOperation(p["operation"].upper()), status=AS.PROPOSED,
                                    proposal=p, po_id=po.get("id"), po_number=po.get("po_number"),
                                    expires_at=A.now() + timedelta(minutes=ttl)))
            db.commit()
        if p["operation"] == "create":
            intro = _t(lang, "propose_create")
        elif p["operation"] == "update":
            intro = _t(lang, "propose_update", po=po["po_number"])
        else:
            key = "propose_delete_now" if p["mode"] == "immediate" else "propose_delete_supplier"
            intro = _t(lang, key, po=po["po_number"], status=po["status"], supplier=po["supplier_name"])
        blocks = [{"type": "text", "text": intro}, {"type": "action", "actionId": action_id}]
        card = action_card(action_id, p)
        meta = {"intent": "po_automation", "language": lang, "evaluated": False, "sources": [],
                "automation": {"action_id": action_id, "operation": p["operation"], "status": "PROPOSED"}}
        final = {"blocks": blocks, "meta": meta, "actions": {action_id: card}}
        message = AIMessage(content=intro, additional_kwargs={"blocks": blocks, "meta": meta,
                                                              "actions": {action_id: card}})
        return {"final": final, "messages": [message], "pending_action": {"id": action_id}}

    def auto_await(state):
        decision = interrupt({"action_id": state["pending_action"]["id"]})
        return {"automation_decision": decision}

    def _execute(action: AutomationAction, lang: str) -> tuple[list[str], AutomationStatus, dict, bool]:
        """Runs the confirmed proposal in one transaction. Returns (texts, status, result, queued_supplier_work)."""
        p = action.proposal
        with A.write_session() as db:
            if p["operation"] == "create":
                texts, created = [], []
                for group in p["purchase_orders"]:
                    po = A.create_and_issue_po(db, group, actor, notes=p.get("notes"))
                    A.queue_conversation(db, po, ConversationPurpose.CONFIRM_ORDER, action.id)
                    created.append({"id": po.id, "po_number": po.po_number, "supplier_name": po.supplier_name,
                                    "total_amount": po.total_amount})
                    texts.append(_t(lang, "create", po=po.po_number, supplier=po.supplier_name,
                                    total=A.rupiah(po.total_amount)))
                texts.append(_t(lang, "create_tail"))
                first = created[0]
                return texts, AS.AWAITING_SUPPLIER, {"created": created, "po_id": first["id"],
                                                     "po_number": first["po_number"]}, True
            if p["operation"] == "update":
                po = A.update_draft_po(db, p)
                return ([_t(lang, "update", po=po.po_number, before=A.rupiah(p["total_before"]),
                             after=A.rupiah(po.total_amount))], AS.EXECUTED, {"total_after": po.total_amount}, False)
            if p["mode"] == "immediate":
                snap = A.delete_po(db, p["po"]["id"], p["po"])
                return [_t(lang, "delete_now", po=snap["po_number"])], AS.EXECUTED, {"deleted": snap["po_number"]}, False
            conv = A.request_po_cancellation(db, p, action.id)
            return ([_t(lang, "delete_supplier", po=p["po"]["po_number"], supplier=p["po"]["supplier_name"])],
                    AS.AWAITING_SUPPLIER, {"conversation_id": conv.id}, True)

    def auto_execute(state):
        lang = state["language"]
        decision = state.get("automation_decision") or {}
        action_id = state["pending_action"]["id"]
        kind = decision.get("decision")
        if kind != "superseded":
            emit("auto_execute", lang)
        with SessionLocal() as db:
            action = db.get(AutomationAction, action_id)
            expired = action.expires_at < A.now()
            if kind == "approve" and not expired:
                db.expunge(action)
            else:
                action.status = {"reject": AS.REJECTED, "superseded": AS.SUPERSEDED}.get(kind, AS.EXPIRED)
                action.decided_at = A.now()
                db.commit()
                status = action.status
        reset = {"pending_action": None, "automation_draft": None, "automation_decision": None}
        if kind == "superseded":
            return {**reset, "final": None}
        if kind != "approve" or expired:
            text = _t(lang, "rejected" if status == AS.REJECTED else "expired")
            return {**reset, **_finish(lang, [text], action_id, UI_STATUS[status])}
        queued = False
        try:
            texts, status, result, queued = _execute(action, lang)
        except AppError as e:
            texts, status, result = [_t(lang, "failed", reason=e.detail)], AS.FAILED, {"error": e.detail}
        except Exception as e:  # noqa: BLE001
            log.exception("automation action %s failed", action_id)
            texts, status, result = [_t(lang, "failed", reason=type(e).__name__)], AS.FAILED, {"error": str(e)}
        with SessionLocal() as db:
            row = db.get(AutomationAction, action_id)
            row.status, row.decided_at = status, A.now()
            row.result = {**(row.result or {}), **result}
            row.po_id = row.po_id or result.get("po_id")
            row.po_number = row.po_number or result.get("po_number")
            db.commit()
        if queued and on_supplier_work is not None:
            emit("supplier_contact", lang)
            on_supplier_work()
        return {**reset, **_finish(lang, texts, action_id, UI_STATUS[status], status.value)}

    def _finish(lang, texts, action_id, ui_status, db_status=None):
        blocks = [{"type": "text", "text": t} for t in texts]
        meta = {"intent": "po_automation", "language": lang, "evaluated": False, "sources": [],
                "automation": {"action_id": action_id, "status": db_status or ui_status}}
        update = {action_id: {"status": ui_status}}
        return {"final": {"blocks": blocks, "meta": meta, "action_updates": update},
                "messages": [AIMessage(content="\n".join(texts),
                                       additional_kwargs={"blocks": blocks, "meta": meta})]}

    for name, fn in [("auto_parse", auto_parse), ("auto_resolve", auto_resolve), ("auto_clarify", auto_clarify),
                     ("auto_propose", auto_propose), ("auto_await", auto_await), ("auto_execute", auto_execute)]:
        g.add_node(name, fn)
    g.add_conditional_edges("auto_parse", lambda s: "auto_resolve" if s["automation_step"] == "resolve" else finalize_name,
                            ["auto_resolve", finalize_name])
    g.add_conditional_edges("auto_resolve", lambda s: "auto_propose" if s["automation_step"] == "resolved" else "auto_clarify",
                            ["auto_propose", "auto_clarify"])
    g.add_edge("auto_clarify", finalize_name)
    g.add_edge("auto_propose", "auto_await")
    g.add_edge("auto_await", "auto_execute")
    g.add_edge("auto_execute", "__end__")
