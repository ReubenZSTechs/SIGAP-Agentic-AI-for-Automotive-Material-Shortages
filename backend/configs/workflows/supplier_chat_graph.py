"""One supplier reply: load context -> analyze (LLM) -> apply decision (tools) -> escalate/revision -> deliver.

Stateless between messages: the conversation, its messages and the PO live in the DB. The agent
only classifies the reply and writes text; which PO is touched and how is decided here.
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.exceptions import AppError
from app.database import SessionLocal
from app.models import PurchaseOrder, Supplier, SupplierConversation
from app.models.enums import AutomationStatus, ConversationPurpose, ConversationStatus, MessageDirection, POStatus
from configs.tools import po_actions as A

CS, P = ConversationStatus, ConversationPurpose
FINAL_CAPTION = ("{po} final telah dikonfirmasi. Terlampir PDF PO final untuk pemeriksaan Anda; "
                 "balas di chat ini bila ada yang tidak sesuai.")
FULFILLABLE = (POStatus.ISSUED, POStatus.PARTIALLY_RECEIVED)


class SupplierTurn(TypedDict, total=False):
    conversation_id: int
    text: str
    context: dict
    analysis: dict
    sends: list[dict]
    escalation: dict | None
    change_request_id: int | None
    result: dict


def build_supplier_reply_graph(svc):
    """`svc` is the `SupplierChatService` (agents, config, transport, delivery)."""
    cfg = svc.cfg

    def load_context(state: SupplierTurn) -> SupplierTurn:
        cid = state["conversation_id"]
        with SessionLocal() as db:
            conv = db.get(SupplierConversation, cid)
            conv.turn_count += 1
            po = db.get(PurchaseOrder, conv.po_id) if conv.po_id else None
            ctx = {"conversation_id": cid, "purpose": conv.purpose.value, "turn_count": conv.turn_count,
                   "supplier_id": conv.supplier_id, "supplier_name": db.get(Supplier, conv.supplier_id).name,
                   "po": A.po_snapshot(po) if po else conv.po_snapshot, "po_exists": po is not None,
                   "po_status": po.status.value if po else None, "action_id": conv.automation_action_id,
                   "chat_id": svc.supplier_chat_id(db, conv.supplier_id)}
            db.commit()
        ctx["messages"] = svc.messages(cid)
        return {"context": ctx, "sends": [], "escalation": None, "change_request_id": None}

    def analyze(state: SupplierTurn) -> SupplierTurn:
        ctx = state["context"]
        po = ctx["po"]
        payload = {"purpose": ctx["purpose"], "supplier_name": ctx["supplier_name"],
                   "po": {"po_number": po["po_number"], "status": ctx["po_status"], "po_date": po["po_date"],
                          "total_amount": po["total_amount"],
                          "lines": [{k: it[k] for k in ("sku", "name", "uom", "qty_ordered", "unit_price", "needed_by_date")}
                                    for it in po["items"]]},
                   "conversation": ctx["messages"][:-1], "latest_supplier_message": state["text"]}
        return {"analysis": svc.run_agent("supplier_reply_agent", payload)}

    def apply_decision(state: SupplierTurn) -> SupplierTurn:
        """Deterministic mapping of the agent's decision to DB tools (see docs/SUPPLIER_TELEGRAM.md)."""
        ctx, a = state["context"], state["analysis"]
        purpose, decision, reply = ctx["purpose"], a["decision"], a["reply_text"]
        escalation, cr_id, result, final_rev = None, None, {"decision": decision}, None
        with A.write_session() as db:
            conv = db.get(SupplierConversation, ctx["conversation_id"])
            po = db.get(PurchaseOrder, conv.po_id) if conv.po_id else None
            if po is None or po.status not in FULFILLABLE:
                A.close_conversation(conv, CS.CLOSED, reason="po_changed")
                reply = f"Terima kasih. {ctx['po']['po_number']} sudah tidak berlaku lagi; tim kami akan menghubungi Anda bila perlu."
                escalation = {"situation": "po_changed", "detail": f"Status PO saat ini: {po.status.value if po else 'dihapus'}"}
            elif purpose in (P.CONFIRM_ORDER.value, P.REVISION_CONFIRM.value):
                if decision == "confirmed":
                    A.record_supplier_confirmation(db, conv, a.get("promised_delivery_date"), a.get("supplier_reference"))
                    rev = A.finalize_po_revision(db, po)              # tanpa perubahan lagi -> versi FINAL + PDF
                    final_rev = {"id": rev.id, "version": rev.version}
                    result["final_revision"] = final_rev
                    A.note_action(db, conv.automation_action_id, AutomationStatus.EXECUTED,
                                  supplier_outcome=f"{po.po_number} dikonfirmasi supplier (versi final {rev.version})")
                elif decision == "declined":
                    A.record_supplier_decline(db, conv, a["reason"])
                    A.note_action(db, conv.automation_action_id, supplier_outcome=f"{po.po_number} ditolak supplier")
                    escalation = {"situation": "declined"}
                elif decision == "change_requested":
                    cr = A.open_change_request(db, conv, a.get("proposed_changes") or [], state["text"],
                                               cfg.get("max_revision_rounds", 2))
                    if cr is not None:
                        cr_id = cr.id
                    else:
                        reply = (f"{reply}\nMohon sebutkan perubahan yang Anda minta secara spesifik "
                                 "(qty, harga satuan, atau tanggal kirim per item).")
            elif decision == "confirmed":                       # CANCEL_ORDER disetujui supplier
                try:
                    A.close_conversation(conv, CS.CANCEL_CONFIRMED, reason=a["reason"])
                    snap = A.delete_po(db, po.id)
                    A.note_action(db, conv.automation_action_id, AutomationStatus.EXECUTED,
                                  supplier_outcome=f"Pembatalan disetujui supplier; {snap['po_number']} dihapus")
                    result["deleted_po"] = snap["po_number"]
                except AppError as e:
                    A.close_conversation(conv, CS.ESCALATED, reason=e.detail)
                    escalation = {"situation": "po_changed", "detail": e.detail}
            elif decision in ("declined", "change_requested"):  # supplier menolak pembatalan
                A.record_supplier_decline(db, conv, a["reason"])
                A.note_action(db, conv.automation_action_id, AutomationStatus.FAILED,
                              supplier_outcome=f"Supplier menolak pembatalan {po.po_number}; diteruskan ke manajer")
                escalation = {"situation": "cancel_refused",
                              "detail": "Mohon hubungi supplier untuk membicarakan pembatalan bila masih diperlukan."}

            open_states = (CS.AWAITING_SUPPLIER,)
            if escalation is None and cr_id is None and conv.status in open_states \
                    and conv.turn_count >= cfg.get("max_turns", 8):
                A.close_conversation(conv, CS.ESCALATED, reason="max_turns")
                escalation = {"situation": "unresolved"}
            result["conversation_status"] = conv.status.value
        sends = [{"chat_id": ctx["chat_id"], "text": reply, "direction": MessageDirection.OUT,
                  "conversation_id": ctx["conversation_id"], "supplier_id": ctx["supplier_id"], "agent_output": a}]
        if final_rev is not None:
            sends.append({"chat_id": ctx["chat_id"], "direction": MessageDirection.OUT,
                          "text": FINAL_CAPTION.format(po=ctx["po"]["po_number"]),
                          "conversation_id": ctx["conversation_id"], "supplier_id": ctx["supplier_id"],
                          "document": {"revision_id": final_rev["id"]}})
        return {"sends": sends, "escalation": escalation, "change_request_id": cr_id, "result": result}

    def escalate(state: SupplierTurn) -> SupplierTurn:
        ctx, esc = state["context"], state["escalation"]
        msgs = ctx["messages"]
        notice = svc.escalation_send(esc["situation"], ctx["po"], ctx["supplier_id"], msgs, ctx["conversation_id"],
                                     esc.get("detail"))
        return {"sends": [*state["sends"], notice]}

    def present_revision(state: SupplierTurn) -> SupplierTurn:
        out = svc.manager_graph.invoke({"kind": "present", "change_request_id": state["change_request_id"]})
        return {"sends": [*state["sends"], *out.get("sends", [])]}

    def deliver(state: SupplierTurn) -> SupplierTurn:
        svc.deliver(state["sends"])
        status = state["result"].get("conversation_status")
        if status not in (CS.AWAITING_SUPPLIER.value, CS.REVISION_REQUESTED.value):
            svc.dispatch_queued()                              # supplier bebas -> percakapan antrean berikutnya
        return {"result": {**state["result"], "change_request_id": state.get("change_request_id"), "handled": True}}

    def after_apply(state: SupplierTurn) -> str:
        if state.get("change_request_id"):
            return "present_revision"
        return "escalate" if state.get("escalation") else "deliver"

    g = StateGraph(SupplierTurn)
    for name, fn in [("load_context", load_context), ("analyze", analyze), ("apply_decision", apply_decision),
                     ("escalate", escalate), ("present_revision", present_revision), ("deliver", deliver)]:
        g.add_node(name, fn)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "analyze")
    g.add_edge("analyze", "apply_decision")
    g.add_conditional_edges("apply_decision", after_apply, ["present_revision", "escalate", "deliver"])
    g.add_edge("escalate", "deliver")
    g.add_edge("present_revision", "deliver")
    g.add_edge("deliver", END)
    graph = g.compile()

    class _Runner:
        """`invoke` returns the turn result instead of the whole state."""
        def invoke(self, inp: dict) -> dict:
            return graph.invoke(inp).get("result", {})

    return _Runner()
