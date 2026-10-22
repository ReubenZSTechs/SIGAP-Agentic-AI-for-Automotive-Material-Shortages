"""Manager side of supplier revisions: present options, interpret the reply, execute the choice.

Entry kinds:
- present: send a change request's options (computed by tools) as Telegram buttons.
- button:  `cr:<id>:<choice>` (direct choice) | `crc:<id>:<choice>` (confirm a free-text choice) | `crx:<id>`.
- text:    free-text reply -> `manager_decision_agent` -> confirm button (never executes directly).
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.core.exceptions import AppError
from app.database import SessionLocal
from app.models import POChangeRequest, SupplierConversation
from app.models.enums import ChangeRequestStatus, ConversationStatus
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
    sends: list[dict]
    execute: bool
    result: dict


def change_request_details(cr: POChangeRequest) -> str:
    """Exact text of what the supplier asked for and what each option does (no LLM numbers)."""
    snap = cr.po_snapshot
    lines = [f"Permintaan revisi #{cr.id} — {cr.po_number} ({snap['supplier_name']}), total saat ini {A.rupiah(snap['total_amount'])}"]
    if cr.proposed_changes:
        lines.append("Perubahan diminta:")
        lines += [f"- {A.describe_change(c)}" for c in cr.proposed_changes]
    if cr.invalid_changes:
        lines.append("Tidak dapat diproses otomatis: " + "; ".join(
            f"{c.get('material_ref')} {c.get('field')}={c.get('new_value')} ({c.get('error')})" for c in cr.invalid_changes))
    lines.append(f'Pesan supplier: "{cr.supplier_message[:300]}"')
    lines.append("Opsi:")
    for n, o in enumerate(cr.options, 1):
        detail = o["effect"]
        if o["key"] == "approve_change":
            detail += f" Total {A.rupiah(o['total_before'])} → {A.rupiah(o['total_after'])}."
        elif o["key"] == "resource":
            detail += " " + "; ".join(
                f"{g['supplier_name']}: {A.rupiah(g['total_amount'])} (lead time maks "
                f"{max(i['lead_time_days'] for i in g['items'])} hari)" for g in o["purchase_orders"])
        lines.append(f"{n}. {o['label']} — {detail}")
    return "\n".join(lines)


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
            payload = {"situation": "revision_request", "po": cr.po_snapshot,
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
                details += f"\nRekomendasi agent: {label} — {out['rationale']}"
        except Exception:  # noqa: BLE001  (opsi tetap dikirim dengan teks standar)
            out, body = None, f"Supplier meminta revisi {payload['po']['po_number']}. Mohon pilih tindakan."
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
            return {"sends": [svc.manager_send(f"Baik, belum ada perubahan untuk permintaan revisi #{cr_id}.")],
                    "execute": False, "result": {"cancelled": cr_id}}
        if kind == "crc" and len(parts) == 3 and not confirm_pending(cr_id, parts[2]):
            return {"sends": [svc.manager_send(f"Konfirmasi ini sudah tidak berlaku untuk permintaan revisi #{cr_id}.")],
                    "execute": False, "result": {"handled": True, "stale_confirmation": cr_id}}
        if kind in ("cr", "crc") and len(parts) == 3:
            return {"change_request_id": cr_id, "choice": parts[2], "execute": True, "sends": []}
        return {"sends": [], "execute": False, "result": {"handled": False, "reason": "bad button"}}

    def on_text(state: ManagerTurn) -> ManagerTurn:
        with SessionLocal() as db:
            pending = [{"id": cr.id, "po_number": cr.po_number, "supplier": cr.supplier.name,
                        "options": [{"key": o["key"], "label": o["label"]} for o in cr.options]}
                       for cr in db.scalars(select(POChangeRequest).where(POChangeRequest.status.in_(PENDING))
                                            .order_by(POChangeRequest.id))]
        if not pending:
            return {"execute": False, "sends": [svc.manager_send(
                "Terima kasih. Saat ini tidak ada permintaan revisi supplier yang menunggu keputusan Anda.")],
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
        with SessionLocal() as db:
            cr = db.get(POChangeRequest, target["id"])
            cr.status, cr.pending_choice = CRS.AWAITING_MANAGER_CONFIRM, out["choice"]
            db.commit()
        label = next(o["label"] for o in target["options"] if o["key"] == out["choice"])
        buttons = [{"label": f"Ya, {label.lower()}", "data": f"crc:{target['id']}:{out['choice']}"},
                   {"label": "Tidak, batalkan", "data": f"crx:{target['id']}"}]
        return {"execute": False, "sends": [svc.manager_send(
            f"{out['reply_text']}\nKonfirmasi: {label} untuk {target['po_number']}?", buttons, out)],
            "result": {"handled": True, "awaiting_confirmation": target["id"], "choice": out["choice"]}}

    def execute(state: ManagerTurn) -> ManagerTurn:
        cr_id, choice = state["change_request_id"], state["choice"]
        try:
            with A.write_session() as db:
                cr = db.get(POChangeRequest, cr_id)
                if cr is None:
                    raise AppError(404, f"Permintaan revisi #{cr_id} tidak ditemukan")
                actor = state.get("actor") or cfg.get("manager_actor", "Manager via Telegram")
                result = A.apply_change_request(db, cr, choice, actor)
                if not state.get("actor"):                     # dari Telegram: catat seperti keputusan Hub
                    from app.hub.common import audit
                    audit(db, actor, "choose", "change_request", cr_id, choice=choice, po_number=cr.po_number,
                          source="telegram")
                notices = [svc.withdrawal_send(db, n["supplier_id"], n["snapshot"], n["conversation_id"])
                           for n in result.pop("notices")]
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
            return {"sends": [svc.manager_send(f"Tidak dapat menjalankan pilihan untuk permintaan #{cr_id}: {e.detail}")],
                    "result": {"handled": True, "error": e.detail}}
        svc.close_manager_buttons(cr_id)
        if choice == "approve_change":
            text = (f"Revisi {result['po_number']} disetujui (versi {result['revision']['version']}); total baru "
                    f"{A.rupiah(result['total_after'])}. Supplier menerima daftar perubahan untuk dikonfirmasi.")
        elif choice == "abort":
            text = f"{result['po_number']} dibatalkan (status Dibatalkan, data tetap tersimpan); supplier telah diberi tahu."
        else:
            text = (f"{result['po_number']} dialihkan ke PO baru: " + "; ".join(
                f"{p['po_number']} ({p['supplier_name']}, {A.rupiah(p['total_amount'])})" for p in result["new_pos"])
                + ". Supplier lama diberi tahu, supplier baru diminta konfirmasi.")
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
