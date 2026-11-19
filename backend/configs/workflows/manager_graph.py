"""Manager side of supplier requests (revision, price, date, cancellation): present options, interpret the
reply, execute the choice.

Entry kinds:
- present: send a change request's options (computed by tools) as Telegram buttons.
- button:  `cr:<id>:<choice>` (direct choice) | `crc:<id>:<choice>` (confirm a free-text choice) | `crx:<id>`.
- text:    free-text reply -> `manager_decision_agent` -> confirm button (never executes directly).
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.core.exceptions import AppError
from app.core.i18n import translate
from app.database import SessionLocal
from app.models import POChangeRequest, SupplierConversation
from app.models.enums import ChangeRequestStatus, ConversationStatus, MessageDirection
from configs.tools import agent_limits as L
from configs.tools import po_actions as A

CRS = ChangeRequestStatus
PENDING = (CRS.PENDING_MANAGER, CRS.AWAITING_MANAGER_CONFIRM)


class ManagerTurn(TypedDict, total=False):
    kind: str
    change_request_id: int | None
    text: str | None
    data: str | None
    choice: str | None
    actor: str | None          # mis. "Rina via Hub"; default dari cfg.manager_actor
    params: dict | None        # counter_prices (negotiate) / schedule_ids (cancel_project), dari Hub
    sends: list[dict]
    execute: bool
    result: dict


KIND_TITLE = {"REVISION": "Revision request", "PRICE_CHANGE": "Price change outside the agent's band",
              "DATE_CHANGE": "Delivery date outside the agent's window", "CANCELLATION": "PO cancelled"}
SITUATION = {"REVISION": "revision_request", "PRICE_CHANGE": "price_change", "DATE_CHANGE": "date_change",
             "CANCELLATION": "supplier_cancellation"}


def change_request_details(cr: POChangeRequest) -> str:
    """Exact text of what the supplier asked for and what each option does (no LLM numbers)."""
    snap = cr.po_snapshot
    lines = [f"{KIND_TITLE.get(cr.kind, 'Request')} #{cr.id} — {cr.po_number} ({snap['supplier_name']}), "
             f"total {A.rupiah(snap['total_amount'])}"]
    if cr.kind == "DATE_CHANGE" and cr.proposed_changes:
        c = cr.proposed_changes[0]
        lines.append(f"Requested delivery date: {c['reason']}")
        if c.get("old"):
            lines.append(f"Current delivery date: {c['old']}")
    elif cr.kind == "CANCELLATION":
        lines.append(f"{cr.po_number} has already been cancelled automatically. Reason: "
                     f"{cr.proposed_changes[0].get('reason') or '-'}")
    elif cr.proposed_changes:
        lines.append("Requested changes:")
        lines += [f"- {A.describe_change(c)}" for c in cr.proposed_changes]
        if cr.kind == "PRICE_CHANGE":
            lines += [f"  ({c['sku']}: {L.price_change_pct(c['old'], c['new']):+.1f}%)" for c in cr.proposed_changes
                      if c["field"] == "unit_price"]
    if cr.invalid_changes:
        lines.append("Could not be processed automatically: " + "; ".join(
            f"{c.get('material_ref')} {c.get('field')}={c.get('new_value')} ({c.get('error')})" for c in cr.invalid_changes))
    lines.append(f'Supplier message: "{cr.supplier_message[:300]}"')
    lines.append("Options:")
    for n, o in enumerate(cr.options, 1):
        detail = o["effect"]
        if o["key"] == "approve_change":
            detail += f" Total {A.rupiah(o['total_before'])} → {A.rupiah(o['total_after'])}."
        elif o["key"] == "resource":
            detail += " " + "; ".join(
                f"{g['supplier_name']}: {A.rupiah(g['total_amount'])} (max lead time "
                f"{max(i['lead_time_days'] for i in g['items'])} days)" for g in o["purchase_orders"])
            if o.get("warnings"):
                detail += " Note: " + "; ".join(o["warnings"])
        elif o["key"] in ("continue_project", "cancel_project") and o.get("schedules"):
            detail += " Schedules: " + ", ".join(f"{x['batch_code']} {x['product']} ({x['production_date']})"
                                              for x in o["schedules"][:6])
        elif o["key"] == "negotiate":
            detail += " Reply with your counter price, e.g. \"nego 12000\"."
        lines.append(f"{n}. {o['label']} — {detail}")
    return "\n".join(lines)


def _counter_from_text(cr: POChangeRequest, counter: list[dict] | None) -> dict | None:
    """manager_decision_agent counter_prices [{material_ref, unit_price}] -> {po_item_id: price} for the CR lines."""
    lines = [c for c in cr.proposed_changes if c["field"] == "unit_price"]
    if not counter or not lines:
        return None
    out = {}
    for entry in counter:
        ref = str(entry.get("material_ref") or "").strip().lower()
        hit = [c for c in lines if c["sku"].lower() == ref or (ref and ref in c["name"].lower())]
        if not hit and len(lines) == 1:
            hit = lines
        for c in hit:
            out[c["po_item_id"]] = int(entry["unit_price"])
    if len(counter) == 1 and len(lines) > 1 and not out:
        out = {c["po_item_id"]: int(counter[0]["unit_price"]) for c in lines}
    return out if len(out) == len(lines) else None


def confirm_pending(cr_id: int, choice: str) -> bool:
    """A `crc:` (Ya) button is valid only while that exact free-text choice still waits for confirmation."""
    with SessionLocal() as db:
        cr = db.get(POChangeRequest, cr_id)
        return cr is not None and cr.status == CRS.AWAITING_MANAGER_CONFIRM and cr.pending_choice == choice


def build_manager_graph(svc):
    cfg = svc.cfg

    def present(state: ManagerTurn) -> ManagerTurn:
        with SessionLocal() as db:
            cr = db.get(POChangeRequest, state["change_request_id"])
            details, options = change_request_details(cr), cr.options
            payload = {"situation": SITUATION.get(cr.kind, "revision_request"), "kind": cr.kind, "po": cr.po_snapshot,
                       "supplier": {"name": cr.supplier.name, "contact": cr.supplier.contact},
                       "supplier_messages": [{"direction": "IN", "text": cr.supplier_message}],
                       "proposed_changes": cr.proposed_changes, "invalid_changes": cr.invalid_changes,
                       "options": options}
            cr_id, conv_id = cr.id, cr.conversation_id
        try:
            out = svc.run_agent("manager_escalation_writer", payload)
            body = out["message_text"]
            if out["recommended_option"] in {o["key"] for o in options}:
                label = next(o["label"] for o in options if o["key"] == out["recommended_option"])
                details += f"\nAgent recommendation: {label} — {out['rationale']}"
        except Exception:  # noqa: BLE001  (opsi tetap dikirim dengan teks standar)
            out, body = None, f"{KIND_TITLE.get(payload.get('kind'), 'Supplier request')}: {payload['po']['po_number']}. Please choose an action."
        buttons = [{"label": o["label"], "data": f"cr:{cr_id}:{o['key']}"} for o in options]
        return {"sends": [svc.manager_send(f"{body}\n\n{details}", buttons, out, conv_id)], "result": {"presented": cr_id}}

    def on_button(state: ManagerTurn) -> ManagerTurn:
        parts = (state.get("data") or "").split(":")
        try:
            kind, cr_id = parts[0], int(parts[1])
        except (IndexError, ValueError):
            return {"sends": [], "execute": False, "result": {"handled": False, "reason": "bad button"}}
        if kind == "crx":
            with SessionLocal() as db:
                cr = db.get(POChangeRequest, cr_id)
                if cr is not None and cr.status == CRS.AWAITING_MANAGER_CONFIRM:
                    cr.status, cr.pending_choice = CRS.PENDING_MANAGER, None
                    db.commit()
            svc.close_manager_buttons(cr_id)                   # tombol Ya/Tidak lama tidak berlaku lagi
            return {"sends": [svc.manager_send(f"OK, nothing has changed for request #{cr_id}.")],
                    "execute": False, "result": {"cancelled": cr_id}}
        if kind == "crc" and len(parts) == 3 and not confirm_pending(cr_id, parts[2]):
            return {"sends": [svc.manager_send(f"This confirmation is no longer valid for request #{cr_id}.")],
                    "execute": False, "result": {"handled": True, "stale_confirmation": cr_id}}
        if kind == "cr" and len(parts) == 3 and parts[2] == "negotiate" and not (state.get("params") or {}).get("counter_prices"):
            with SessionLocal() as db:                         # tombol tidak membawa harga: minta lewat teks
                cr = db.get(POChangeRequest, cr_id)
                if cr is None or cr.status not in PENDING:
                    return {"sends": [svc.manager_send(f"Request #{cr_id} has already been processed.")], "execute": False,
                            "result": {"handled": True}}
                lines = ", ".join(f"{c['sku']} (asked {A.rupiah(c['new'])}, was {A.rupiah(c['old'])})"
                                  for c in cr.proposed_changes if c["field"] == "unit_price")
            return {"execute": False, "result": {"handled": True, "awaiting_counter": cr_id}, "sends": [svc.manager_send(
                f"Reply with your counter price for {lines}, e.g. \"nego 12000\" (or per SKU: \"nego SKU-1 12000, SKU-2 9500\").")]}
        if kind in ("cr", "crc") and len(parts) == 3:
            return {"change_request_id": cr_id, "choice": parts[2], "execute": True, "sends": []}
        return {"sends": [], "execute": False, "result": {"handled": False, "reason": "bad button"}}

    def on_text(state: ManagerTurn) -> ManagerTurn:
        with SessionLocal() as db:
            pending = [{"id": cr.id, "kind": cr.kind, "po_number": cr.po_number, "supplier": cr.supplier.name,
                        "options": [{"key": o["key"], "label": o["label"]} for o in cr.options],
                        "price_lines": [{"sku": c["sku"], "name": c["name"], "old": c["old"], "asked": c["new"]}
                                        for c in cr.proposed_changes if c["field"] == "unit_price"]}
                       for cr in db.scalars(select(POChangeRequest).where(POChangeRequest.status.in_(PENDING))
                                            .order_by(POChangeRequest.id))]
        if not pending:
            return {"execute": False, "sends": [svc.manager_send(
                "Thank you. There are no supplier requests waiting for your decision right now.")],
                "result": {"handled": True, "pending": 0}}
        out = svc.run_agent("manager_decision_agent", {"message": state["text"], "pending_requests": pending})
        target = next((p for p in pending if p["id"] == out.get("change_request_id")), None)
        if target is None and len(pending) == 1:
            target = pending[0]
        valid = target is not None and out["choice"] in {o["key"] for o in target["options"]}
        if not valid:
            buttons = [{"label": f"{p['po_number']}: {o['label']}", "data": f"cr:{p['id']}:{o['key']}"}
                       for p in pending for o in p["options"]][:9]
            return {"execute": False, "sends": [svc.manager_send(out["reply_text"], buttons, out)],
                    "result": {"handled": True, "understood": False}}
        counter_note = ""
        with SessionLocal() as db:
            cr = db.get(POChangeRequest, target["id"])
            if out["choice"] == "negotiate":
                counter = _counter_from_text(cr, out.get("counter_prices"))
                if counter is None:
                    return {"execute": False, "sends": [svc.manager_send(
                        "Please state the counter price per SKU, e.g. \"nego 12000\" or \"nego SKU-1 12000, SKU-2 9500\".")],
                        "result": {"handled": True, "understood": False}}
                cr.result = {**(cr.result or {}), "pending_counter": counter}
                counter_note = " (" + ", ".join(f"{c['sku']} {A.rupiah(counter[c['po_item_id']])}"
                                                for c in cr.proposed_changes if c["po_item_id"] in counter) + ")"
            cr.status, cr.pending_choice = CRS.AWAITING_MANAGER_CONFIRM, out["choice"]
            db.commit()
        label = next(o["label"] for o in target["options"] if o["key"] == out["choice"]) + counter_note
        buttons = [{"label": f"Yes, {label.lower()}", "data": f"crc:{target['id']}:{out['choice']}"},
                   {"label": "No, cancel", "data": f"crx:{target['id']}"}]
        return {"execute": False, "sends": [svc.manager_send(
            f"{out['reply_text']}\nConfirm: {label} for {target['po_number']}?", buttons, out)],
            "result": {"handled": True, "awaiting_confirmation": target["id"], "choice": out["choice"]}}

    def execute(state: ManagerTurn) -> ManagerTurn:
        cr_id, choice = state["change_request_id"], state["choice"]
        try:
            with A.write_session() as db:
                cr = db.get(POChangeRequest, cr_id)
                if cr is None:
                    raise AppError(404, f"Request #{cr_id} not found")
                actor = state.get("actor") or cfg.get("manager_actor", "Manager via Telegram")
                result = A.apply_change_request(db, cr, choice, actor, state.get("params"))
                if not state.get("actor"):                     # dari Telegram: catat seperti keputusan Hub
                    from app.hub.audit_log import record
                    record(db, actor, "choose", "change_request", cr_id, choice=choice, po_number=cr.po_number,
                           supplier_id=cr.supplier_id, source="telegram", kind=cr.kind,
                           summary=f"{A.OPTION_LABEL.get(choice, choice)} for {cr.po_number} "
                                   f"({KIND_TITLE.get(cr.kind, cr.kind).lower()})")
                notices = [svc.withdrawal_send(db, n["supplier_id"], n["snapshot"], n["conversation_id"])
                           for n in result.pop("notices")]
                notices += [{"chat_id": svc.supplier_chat_id(db, m["supplier_id"]), "text": m["text"],
                             "direction": MessageDirection.OUT, "conversation_id": m["conversation_id"],
                             "supplier_id": m["supplier_id"], "agent_output": {"source": "manager_decision", "cr": cr_id},
                             **({"document": {"revision_id": m["revision_id"]}} if m.get("revision_id") else {})}
                            for m in result.pop("supplier_messages")]
        except AppError as e:
            with SessionLocal() as db:                         # PO berubah / sudah diproses -> catat & lepas blokir
                cr = db.get(POChangeRequest, cr_id)
                if cr is not None and cr.status in PENDING:
                    cr.status, cr.result = CRS.FAILED, {"error": e.detail}
                    conv = db.get(SupplierConversation, cr.conversation_id) if cr.conversation_id else None
                    if conv is not None and conv.status == ConversationStatus.REVISION_REQUESTED:
                        A.close_conversation(conv, ConversationStatus.ESCALATED, reason=e.detail)
                db.commit()
            svc.close_manager_buttons(cr_id)
            return {"sends": [svc.manager_send(f"Could not run the choice for request #{cr_id}: {translate(e.detail, 'en')}")],
                    "result": {"handled": True, "error": e.detail}}
        svc.close_manager_buttons(cr_id)
        if choice == "approve_change":
            text = (f"Revision of {result['po_number']} approved (version {result['revision']['version']}); new total "
                    f"{A.rupiah(result['total_after'])}. The supplier received the changes to confirm.")
        elif choice == "negotiate":
            text = (f"Counter price for {result['po_number']} sent to the supplier (version {result['revision']['version']}, "
                    f"total {A.rupiah(result['total_after'])}). The supplier is asked to confirm.")
        elif choice == "accept_date":
            text = (f"New delivery date for {result['po_number']} accepted; PO version {result['revision']['version']} "
                    "was sent to the supplier.")
        elif choice == "reject_date":
            text = f"New delivery date for {result['po_number']} rejected; the supplier has been informed."
        elif choice == "abort":
            text = f"{result['po_number']} cancelled (status Cancelled, data kept); the supplier has been informed."
        elif choice == "continue_project":
            text = (f"Project continues without a replacement for {result['po_number']}. The material shortage shows "
                    "in MPS & Planning (run marked for re-planning); please find another source manually.")
        elif choice == "cancel_project":
            text = "Production schedules cancelled: " + ", ".join(result.get("cancelled_schedules") or ["-"]) + "."
        elif result.get("kind") == "CANCELLATION":
            text = ("Replacement PO for " + result["po_number"] + " issued: " + "; ".join(
                f"{p['po_number']} ({p['supplier_name']}, {A.rupiah(p['total_amount'])})" for p in result["new_pos"])
                + ". The agent is contacting the new supplier for confirmation.")
        else:
            text = (f"{result['po_number']} moved to new PO(s): " + "; ".join(
                f"{p['po_number']} ({p['supplier_name']}, {A.rupiah(p['total_amount'])})" for p in result["new_pos"])
                + ". The previous supplier was informed; the new supplier is asked to confirm.")
        return {"sends": [svc.manager_send(text), *notices], "result": {"handled": True, **result}}

    def deliver(state: ManagerTurn) -> ManagerTurn:
        if state.get("kind") != "present":                     # 'present' dikirim oleh pemanggil (urutan pesan)
            svc.deliver(state.get("sends", []))
            if state.get("result", {}).get("queued_conversations") or state.get("result", {}).get("choice"):
                svc.dispatch_queued()
        return {}

    g = StateGraph(ManagerTurn)
    for name, fn in [("present", present), ("on_button", on_button), ("on_text", on_text),
                     ("execute", execute), ("deliver", deliver)]:
        g.add_node(name, fn)
    g.add_conditional_edges(START, lambda s: {"present": "present", "button": "on_button"}.get(s["kind"], "on_text"),
                            ["present", "on_button", "on_text"])
    g.add_edge("present", "deliver")
    g.add_conditional_edges("on_button", lambda s: "execute" if s.get("execute") else "deliver", ["execute", "deliver"])
    g.add_edge("on_text", "deliver")
    g.add_edge("execute", "deliver")
    g.add_edge("deliver", END)
    graph = g.compile()

    class _Runner:
        """`invoke` returns {sends, ...result}; for kind=present the caller delivers the sends."""
        def invoke(self, inp: dict) -> dict:
            out = graph.invoke(inp)
            return {**out.get("result", {}), "sends": out.get("sends", []) if inp.get("kind") == "present" else []}

    return _Runner()
