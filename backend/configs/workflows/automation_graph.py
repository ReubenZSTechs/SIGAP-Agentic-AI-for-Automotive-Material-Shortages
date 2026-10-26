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

from app.chatbot import tracing
from app.chatbot.progress import emit
from app.core.i18n import translate, translate_card, translate_table
from app.core.exceptions import AppError
from sqlalchemy import select

from app.database import SessionLocal
from app.hub.audit_log import record as record_audit
from app.models import AutomationAction, HubMission
from app.models.enums import AutomationOperation, AutomationStatus, ConversationPurpose
from configs.tools import po_actions as A

log = logging.getLogger(__name__)
AS = AutomationStatus
DECIDER = "Pengguna Dashboard"          # keputusan kartu usulan di chat Dashboard (MVP tanpa login)

TEXT = {
    "id": {
        "refused": "Permintaan ini tidak dapat dijalankan: {reason}",
        "gave_up": "Maaf, detail permintaan PO belum lengkap setelah beberapa kali klarifikasi. Silakan ulangi "
                   "permintaan dengan lengkap (material, jumlah, dan supplier bila ada) atau gunakan halaman Manual PO.",
        "cancelled": "Baik, permintaan PO dibatalkan. Tidak ada data yang diubah.",
        "rejected": "Baik, usulan tidak dijalankan. Tidak ada data yang diubah.",
        "missions": "Agent membuat {missions} di Hub Supplier → Misi lebih dulu, lalu menghubungi supplier; pantau "
                    "progres konfirmasinya di sana.",
        "expired": "Usulan ini sudah kedaluwarsa. Silakan kirim ulang permintaannya.",
        "failed": "Perubahan gagal dijalankan: {reason}",
        "update": "{po} diperbarui. Total {before} → {after}.",
        "delete_now": "{po} dihapus. Stok on-order dan planning disesuaikan.",
        "delete_supplier": "Permintaan pembatalan {po} dikirim ke {supplier} via Telegram. PO akan dibatalkan setelah "
                           "supplier menyetujui; bila supplier menolak, manajer akan diberi tahu.",
        "propose_create": "Saya siapkan PO berikut. Periksa lalu konfirmasi:",
        "propose_produce": "Saya cek kebutuhan material untuk jadwal produksi ini. Periksa lalu konfirmasi:",
        "propose_update": "Saya siapkan perubahan {po} berikut. Periksa lalu konfirmasi:",
        "propose_delete_now": "{po} ({status}) belum dikirim ke supplier, jadi akan langsung dihapus. Konfirmasi?",
        "propose_delete_supplier": "{po} sudah diterbitkan ke {supplier}. Saya akan meminta persetujuan pembatalan "
                                   "via Telegram dan membatalkannya (data PO tetap tersimpan) setelah supplier setuju. Konfirmasi?",
        "pay_summary": "Total yang harus dibayar: {total} · pembayaran terakhir {last} · semua material tiba paling lambat {arrival}.",
        "ready_ok": "Semua material siap paling lambat {date} (target produksi {target}).",
        "ready_late": "Target {target} tidak dapat dipenuhi: material baru lengkap paling cepat {date}. Saya sarankan "
                      "produksi pada {date}. Usulan di bawah tetap memakai tanggal {target} bila Anda ingin melanjutkan.",
        "suggest_label": "Jadwalkan pada {date}",
        "suggest_msg": "Produksi {what}, materialnya siap tanggal {date}",
        "card_produce": "Jadwal baru: {what} pada {date}; {n} PO ke {n} supplier. Supplier dihubungi via Telegram setelah dikonfirmasi.",
        "card_produce_none": "Jadwal baru: {what} pada {date}; material cukup, tanpa PO baru.",
        "card_create": "Supplier dihubungi via Telegram setelah dikonfirmasi.",
        "done_produce": "Disetujui. {schedules} dibuat dan {n} PO diterbitkan ke {n} supplier ({pos}), total yang harus "
                        "dibayar {total}. Semua material diperkirakan tiba paling lambat {arrival}; pembayaran terakhir {last}. "
                        "Agent akan menghubungi setiap supplier via Telegram untuk konfirmasi.",
        "done_produce_none": "Disetujui. {schedules} dibuat. Material cukup, jadi tidak ada PO baru.",
        "done_create": "Disetujui. {n} PO diterbitkan ke {n} supplier ({pos}), total yang harus dibayar {total}. Semua "
                       "material diperkirakan tiba paling lambat {arrival}; pembayaran terakhir {last}. Agent akan "
                       "menghubungi setiap supplier via Telegram untuk konfirmasi.",
        "schedule_item": "jadwal {batch} ({qty} {name}, {date})",
        "done_table": "PO yang diterbitkan",
    },
    "en": {
        "refused": "This request cannot be carried out: {reason}",
        "gave_up": "Sorry, the PO request is still incomplete after several clarifications. Please send it again with "
                   "all details (material, quantity, and supplier if any) or use the Manual PO page.",
        "cancelled": "OK, the PO request was cancelled. Nothing was changed.",
        "rejected": "OK, the proposal was not executed. Nothing was changed.",
        "missions": "The agent first created {missions} in Supplier Hub → Missions and then contacts the suppliers; "
                    "track the confirmation progress there.",
        "expired": "This proposal has expired. Please send the request again.",
        "failed": "The change failed: {reason}",
        "update": "{po} was updated. Total {before} → {after}.",
        "delete_now": "{po} was deleted. On-order stock and planning were adjusted.",
        "delete_supplier": "A cancellation request for {po} was sent to {supplier} on Telegram. The PO is cancelled (kept on record) once "
                           "the supplier agrees; if they refuse, the manager is notified.",
        "propose_create": "I prepared the following PO. Please review and confirm:",
        "propose_produce": "I checked the materials needed for this production schedule. Please review and confirm:",
        "propose_update": "I prepared these changes to {po}. Please review and confirm:",
        "propose_delete_now": "{po} ({status}) was never sent to the supplier, so it will be deleted right away. Confirm?",
        "propose_delete_supplier": "{po} was already issued to {supplier}. I will ask them on Telegram to agree to the "
                                   "cancellation and cancel it (kept on record) once they do. Confirm?",
        "pay_summary": "Total to pay: {total} · last payment {last} · all materials arrive by {arrival}.",
        "ready_ok": "All materials are ready by {date} (production target {target}).",
        "ready_late": "The target {target} cannot be met: the materials are complete on {date} at the earliest. I suggest "
                      "producing on {date}. The proposal below still uses {target} if you want to go ahead anyway.",
        "suggest_label": "Schedule on {date}",
        "suggest_msg": "Produce {what}, materials ready on {date}",
        "card_produce": "New schedule: {what} on {date}; {n} POs to {n} suppliers. Suppliers are contacted on Telegram after confirmation.",
        "card_produce_none": "New schedule: {what} on {date}; enough material, no new PO.",
        "card_create": "The supplier is contacted on Telegram after confirmation.",
        "done_produce": "Approved. {schedules} was created and {n} POs were issued to {n} suppliers ({pos}), total to pay "
                        "{total}. All materials are expected by {arrival}; last payment {last}. The agent will contact "
                        "each supplier on Telegram to confirm.",
        "done_produce_none": "Approved. {schedules} was created. There is enough material, so no new PO is needed.",
        "done_create": "Approved. {n} POs were issued to {n} suppliers ({pos}), total to pay {total}. All materials are "
                       "expected by {arrival}; last payment {last}. The agent will contact each supplier on Telegram to confirm.",
        "schedule_item": "schedule {batch} ({qty} {name}, {date})",
        "done_table": "Issued POs",
    },
}


def _t(lang: str, key: str, **kw) -> str:
    return TEXT.get(lang, TEXT["id"])[key].format(**kw)


def _text_draft(*texts: str) -> dict:
    return {"blocks": [{"type": "text", "text": t} for t in texts if t], "claims": [], "insufficient_data": False}


def _table(title: str, columns: list[str], rows: list[list]) -> dict:
    return {"type": "table", "title": title, "columns": columns, "rows": rows}


def payment_table(p: dict) -> list[dict]:
    """"Jadwal pembayaran": when each supplier must be paid (Net N after arrival), shown before anything is sent."""
    pay = p.get("payment")
    if not pay or not pay["rows"]:
        return []
    rows = [[r["supplier_name"], r["materials"], A.rupiah(r["amount"]),
             f"Net {r['payment_term_days']}" if r["payment_term_days"] else "Tunai", r["arrival_date"], r["pay_by"]]
            for r in pay["rows"]]
    rows.append(["Total yang harus dibayar", "", A.rupiah(pay["total"]), "", pay["latest_arrival"], pay["last_pay_by"]])
    return [_table("Jadwal pembayaran", ["Supplier", "Material", "Jumlah", "Termin", "Perkiraan tiba",
                                         "Bayar paling lambat"], rows)]


def payment_summary(p: dict, lang: str) -> str:
    """One line: total to pay, last payment date, latest arrival of all materials."""
    pay = p.get("payment")
    if not pay or not pay["rows"]:
        return ""
    return _t(lang, "pay_summary", total=A.rupiah(pay["total"]), last=pay["last_pay_by"], arrival=pay["latest_arrival"])


def proposal_tables(p: dict) -> list[dict]:
    """Rendered tables of a proposal (shown in the chat and inside the action card)."""
    cols = ["Material", "Qty", "Harga", "Subtotal", "Dibutuhkan"]       # nama material, bukan kode SKU

    def rows(items):
        return [[i["name"], f"{A.fmt_qty(i['qty_ordered'])} {i.get('uom', '')}".strip(), A.rupiah(i["unit_price"]),
                 A.rupiah(i["line_total"]), i.get("needed_by_date") or "–"] for i in items]

    def po_tables(groups):
        return [_table(f"{g['supplier_name']} · Net {g['payment_term_days']} · total "
                       f"{A.rupiah(g['total_amount'])}" + (f" · {len(g['items'])} material dalam 1 PO" if len(g["items"]) > 1 else ""),
                       cols, rows(g["items"])) for g in groups]

    if p["operation"] == "create":
        return [*po_tables(p["purchase_orders"]), *payment_table(p)]
    if p["operation"] == "produce":
        what = ", ".join(f"{A.fmt_qty(s['qty'])} {s['name']}" for s in p["schedules"])
        check = [[m["name"], f"{A.fmt_qty(m['requirement'])} {m['uom']}", A.fmt_qty(m["available"]),
                  A.fmt_qty(m["incoming_in_time"]), A.fmt_qty(m["shortfall"]) if m["shortfall"] else "–",
                  m["status_without_po"]] for m in p["materials"]]
        return [_table(f"Cek material untuk {what} · siap {p['needed_by_date']}",
                       ["Material", "Kebutuhan", "Tersedia", "Masuk tepat waktu", "Kurang (ke batas aman)",
                        "Status tanpa PO baru"], check), *po_tables(p["purchase_orders"]), *payment_table(p)]
    if p["operation"] == "update":
        return [_table(f"{p['po']['po_number']} setelah perubahan · total {A.rupiah(p['total_before'])} → "
                       f"{A.rupiah(p['total_after'])}", cols, rows(p["items_after"]))]
    return [_table(f"{p['po']['po_number']} · {p['po']['supplier_name']} · {p['po']['status']} · total "
                   f"{A.rupiah(p['po']['total_amount'])}", cols, rows(p["po"]["items"]))]


def action_card(action_id: str, p: dict, status: str = "pending", lang: str = "id") -> dict:
    op = p["operation"]
    if op == "produce":
        pos, what = p["purchase_orders"], ", ".join(f"{A.fmt_qty(s['qty'])} {s['name']}" for s in p["schedules"])
        title, approve = "Jadwal produksi & PO", "Konfirmasi jadwal & PO"
        if pos:
            detail = f"{_t(lang, 'card_produce', what=what, date=p['needed_by_date'], n=len(pos))} {payment_summary(p, lang)}"
        else:
            detail = _t(lang, "card_produce_none", what=what, date=p["needed_by_date"])
    elif op == "create":
        title = "Buat & terbitkan PO" + (f" ({len(p['purchase_orders'])} supplier)" if len(p["purchase_orders"]) > 1 else "")
        detail = f"{payment_summary(p, lang)} {_t(lang, 'card_create')}"
        approve = "Konfirmasi & terbitkan"
    elif op == "update":
        title, approve = f"Ubah {p['po']['po_number']}", "Konfirmasi perubahan"
        detail = f"Total {A.rupiah(p['total_before'])} → {A.rupiah(p['total_after'])}."
    else:
        title, approve = f"Hapus {p['po']['po_number']}", "Konfirmasi hapus"
        detail = ("Langsung dihapus (belum dikirim ke supplier)." if p["mode"] == "immediate"
                  else "Minta persetujuan pembatalan ke supplier via Telegram, lalu batalkan (tetap tersimpan).")
    return {"id": action_id, "kind": op, "title": title, "detail": detail, "approveLabel": approve,
            "status": status, "tables": proposal_tables(p), "warnings": p.get("warnings") or []}


UI_STATUS = {AS.PROPOSED: "pending", AS.EXECUTED: "approved", AS.AWAITING_SUPPLIER: "approved",
             AS.REJECTED: "rejected", AS.SUPERSEDED: "expired", AS.EXPIRED: "expired", AS.FAILED: "failed"}


class PoAutomationWorkflow:
    """PO branch of the chat graph: one method per node, added to the shared `ChatState` graph by `add_to()`."""

    def __init__(self, agents: dict, cfg: dict, finalize_name: str = "finalize", on_supplier_work=None):
        self.agents = agents
        self.ttl = cfg.get("proposal_ttl_minutes", 30)
        self.max_rounds = cfg.get("max_clarify_rounds", 3)
        self.actor = cfg.get("actor", "Agent MRP (dikonfirmasi pengguna)")
        self.finalize_name = finalize_name
        self.on_supplier_work = on_supplier_work

    # ------------------------------------------------------------ 1. understand and match the request
    def auto_parse(self, state):
        """LLM: turn the message into a structured PO request (merged with the draft of earlier turns)."""
        emit("auto_parse", state["language"])
        pending = state.get("automation_draft") or {}
        payload = {"latest_message": state["question"], "rewritten": state["rewritten"],
                   "current_draft": pending.get("request"), "last_clarification": pending.get("last_clarification")}
        out = self.agents["automation_parser"].run(json.dumps(payload, ensure_ascii=False),
                                                   today=date.today().isoformat())
        rounds = pending.get("rounds", 0)
        if out["user_cancelled"] or out["operation"] == "none" and pending:
            return {"automation_draft": None, "draft": _text_draft(_t(state["language"], "cancelled")),
                    "automation_step": "done"}
        request = {k: out[k] for k in ("operation", "po_reference", "items", "supplier_query", "needed_by_date", "notes")}
        if out["is_new_request"]:
            rounds = 0                                         # permintaan baru: hitungan klarifikasi mulai lagi
        else:
            request = self._drop_stale_supplier(request, pending.get("request"))
        return {"automation_draft": {"request": request, "rounds": rounds, "last_clarification": None},
                "automation_step": "resolve"}

    @staticmethod
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

    def auto_resolve(self, state):
        """Deterministic: match the request against the database (read-only)."""
        emit("auto_resolve", state["language"])
        draft = state["automation_draft"]
        with tracing.record_tool("resolve_po_request", "read", draft["request"]) as run, SessionLocal() as db:
            res = A.resolve_po_request(db, draft["request"])
            run.done({"status": res["status"], "missing": res.get("missing"), "errors": res.get("errors")})
        return {"automation_resolution": res, "automation_step": res["status"]}

    def auto_clarify(self, state):
        """Asks for what is missing or ambiguous (with clickable options), or explains a refusal."""
        from configs.workflows.chat_graph import LANGUAGE_NAMES   # import lokal: hindari impor melingkar
        lang = state["language"]
        emit("auto_clarify", lang)
        draft, res = state["automation_draft"], state["automation_resolution"]
        if res["status"] == "refused":
            return {"automation_draft": None, "draft": _text_draft(_t(lang, "refused", reason=res["refusal"]))}
        if draft["rounds"] >= self.max_rounds:
            return {"automation_draft": None, "draft": _text_draft(_t(lang, "gave_up"))}
        allowed = {o["value"]: o for a in res["ambiguous"] for o in a["options"]}
        out = self.agents["automation_clarifier"].run(
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

    # ------------------------------------------------------------ 2. confirmation card
    def auto_propose(self, state):
        """Saves the proposal (`automation_actions`) and shows the confirmation card."""
        lang = state["language"]
        emit("auto_propose", lang)
        p = state["automation_resolution"]["proposal"]
        action_id = uuid.uuid4().hex
        po = p.get("po") or {}
        with SessionLocal() as db:
            db.add(AutomationAction(id=action_id, thread_id=state.get("thread_id") or "-",
                                    operation=AutomationOperation(p["operation"].upper()), status=AS.PROPOSED,
                                    proposal=p, po_id=po.get("id"), po_number=po.get("po_number"),
                                    expires_at=A.now() + timedelta(minutes=self.ttl)))
            db.commit()
        extra = []                                            # blok tambahan (mis. tombol tanggal alternatif)
        if p["operation"] == "create":
            intro = f"{_t(lang, 'propose_create')}\n{payment_summary(p, lang)}"
        elif p["operation"] == "produce":
            intro, extra = self._produce_intro(p, lang)
        elif p["operation"] == "update":
            intro = _t(lang, "propose_update", po=po["po_number"])
        else:
            key = "propose_delete_now" if p["mode"] == "immediate" else "propose_delete_supplier"
            intro = _t(lang, key, po=po["po_number"], status=po["status"], supplier=po["supplier_name"])
        blocks = [{"type": "text", "text": intro}, *extra, {"type": "action", "actionId": action_id}]
        card = translate_card(action_card(action_id, p, lang=lang), lang)
        meta = {"intent": "po_automation", "language": lang, "evaluated": False, "sources": [],
                "automation": {"action_id": action_id, "operation": p["operation"], "status": "PROPOSED"}}
        final = {"blocks": blocks, "meta": meta, "actions": {action_id: card}}
        message = AIMessage(content=intro, additional_kwargs={"blocks": blocks, "meta": meta,
                                                              "actions": {action_id: card}})
        return {"final": final, "messages": [message], "pending_action": {"id": action_id}}

    @staticmethod
    def _produce_intro(p: dict, lang: str) -> tuple[str, list[dict]]:
        """Intro for a production card: ready date (or the earliest feasible date + a button to use it) and payment."""
        lines = [_t(lang, "propose_produce")]
        extra = []
        if p.get("feasible", True):
            lines.append(_t(lang, "ready_ok", date=p.get("expected_ready_date"), target=p["needed_by_date"]))
        else:
            date_ok = p["earliest_ready_date"]
            what = ", ".join(f"{A.fmt_qty(s['qty'])} {s['name']}" for s in p["schedules"])
            lines.append(_t(lang, "ready_late", target=p["needed_by_date"], date=date_ok))
            extra.append({"type": "options", "options": [{"label": _t(lang, "suggest_label", date=date_ok),
                                                          "value": _t(lang, "suggest_msg", what=what, date=date_ok)}]})
        if p["purchase_orders"]:
            lines.append(payment_summary(p, lang))
        return "\n".join(lines), extra

    def auto_await(self, state):
        """Pauses the graph until the user answers the card (approve / reject / superseded)."""
        decision = interrupt({"action_id": state["pending_action"]["id"]})
        return {"automation_decision": decision}

    # ------------------------------------------------------------ 3. execute
    def _execute(self, action: AutomationAction, lang: str) -> tuple[list[str], AutomationStatus, dict, bool]:
        """Runs the confirmed proposal in one transaction. Returns (texts, status, result, queued_supplier_work)."""
        p = action.proposal
        with tracing.record_tool(f"{p['operation']}_po", "write", {"action_id": action.id}) as run, \
                A.write_session() as db:
            out = self._execute_in(db, action, p, lang)
            run.done(out[2])
            return out

    def _execute_in(self, db, action: AutomationAction, p: dict, lang: str):
        """Body of `_execute` (inside the write transaction)."""
        if p["operation"] == "produce":
            return self._execute_produce(db, action, p, lang)
        if p["operation"] == "create":
            created = []
            for group in p["purchase_orders"]:
                po = A.create_and_issue_po(db, group, self.actor, notes=p.get("notes"))
                A.queue_conversation(db, po, ConversationPurpose.CONFIRM_ORDER, action.id)
                created.append({"id": po.id, "po_number": po.po_number, "supplier_name": po.supplier_name,
                                "total_amount": po.total_amount})
            first = created[0]
            return (self._approval_summary(p, created, [], lang), AS.AWAITING_SUPPLIER,
                    {"created": created, "po_id": first["id"], "po_number": first["po_number"]}, True)
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

    def _execute_produce(self, db, action: AutomationAction, p: dict, lang: str):
        """Schedule(s) + one ISSUED PO per supplier, in the caller's single transaction."""
        from app.services import schedule_service
        current = A.resolve_po_request(db, p["request"])
        if current["status"] != "resolved" or A.produce_signature(current["proposal"]) != A.produce_signature(p):
            raise AppError(409, "stok, PO, atau harga berubah sejak usulan dibuat; kirim ulang permintaannya")
        batches, created = [], []
        for sch in p["schedules"]:
            s = schedule_service.create_schedule(db, sch["product_id"], date.fromisoformat(sch["production_date"]),
                                                 sch["qty"])
            batches.append({"id": s.id, "batch_code": s.batch_code, "product": sch["name"], "qty": sch["qty"],
                            "date": sch["production_date"]})
        codes = ", ".join(b["batch_code"] for b in batches)
        for group in p["purchase_orders"]:
            po = A.create_and_issue_po(db, group, self.actor, notes=f"Untuk {codes}")
            A.queue_conversation(db, po, ConversationPurpose.CONFIRM_ORDER, action.id)
            created.append({"id": po.id, "po_number": po.po_number, "supplier_name": po.supplier_name,
                            "total_amount": po.total_amount})
        texts = self._approval_summary(p, created, batches, lang)
        result = {"schedules": batches, "created": created}
        if created:
            result.update(po_id=created[0]["id"], po_number=created[0]["po_number"])
        return texts, (AS.AWAITING_SUPPLIER if created else AS.EXECUTED), result, bool(created)

    @staticmethod
    def _approval_summary(p: dict, created: list[dict], batches: list[dict], lang: str) -> list:
        """One summary paragraph (+ a table of the issued POs with their payment dates) after approval."""
        schedules = ", ".join(_t(lang, "schedule_item", batch=b["batch_code"], qty=A.fmt_qty(b["qty"]), name=b["product"],
                                 date=b["date"]) for b in batches)
        if not created:
            return [_t(lang, "done_produce_none", schedules=schedules)]
        pay = p.get("payment") or {"rows": [], "total": sum(c["total_amount"] for c in created),
                                   "last_pay_by": "–", "latest_arrival": "–"}
        kw = {"n": len(created), "pos": ", ".join(c["po_number"] for c in created), "total": A.rupiah(pay["total"]),
              "arrival": pay["latest_arrival"], "last": pay["last_pay_by"]}
        text = _t(lang, "done_produce", schedules=schedules, **kw) if batches else _t(lang, "done_create", **kw)
        by_supplier = {r["supplier_name"]: r for r in pay["rows"]}
        rows = []
        for c in created:
            r = by_supplier.get(c["supplier_name"], {})
            term = r.get("payment_term_days")
            rows.append([c["po_number"], c["supplier_name"], A.rupiah(c["total_amount"]),
                         (f"Net {term}" if term else "Tunai") if term is not None else "–", r.get("pay_by", "–")])
        table = _table(_t(lang, "done_table"), ["No. PO", "Supplier", "Total", "Termin", "Bayar paling lambat"], rows)
        return [text, translate_table(table, lang)]

    def auto_execute(self, state):
        """Applies the user's decision: approve -> execute in one transaction; otherwise mark the card."""
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
                if kind == "reject":
                    record_audit(db, DECIDER, "reject_automation", "automation", action.id, actor_type="MANAGER",
                                 summary=f"Usulan chat ditolak: {(action.proposal or {}).get('operation', '-')} PO",
                                 po_number=action.po_number)
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
            texts, status, result, queued = self._execute(action, lang)
        except AppError as e:
            texts, status, result = [_t(lang, "failed", reason=translate(e.detail, lang))], AS.FAILED, {"error": e.detail}
        except Exception as e:  # noqa: BLE001
            log.exception("automation action %s failed", action_id)
            texts, status, result = [_t(lang, "failed", reason=type(e).__name__)], AS.FAILED, {"error": str(e)}
        with SessionLocal() as db:
            row = db.get(AutomationAction, action_id)
            row.status, row.decided_at = status, A.now()
            row.result = {**(row.result or {}), **result}
            row.po_id = row.po_id or result.get("po_id")
            row.po_number = row.po_number or result.get("po_number")
            record_audit(db, DECIDER, "approve_automation", "automation", action_id, actor_type="MANAGER",
                         summary=f"Usulan chat disetujui: {action.proposal.get('operation', '-')} PO "
                                 + ", ".join(c["po_number"] for c in result.get("created", [])) + f" ({status.value})",
                         po_number=row.po_number)
            missions = [m.id for m in db.scalars(select(HubMission).where(HubMission.automation_action_id == action_id))]
            db.commit()
        if missions and texts and isinstance(texts[0], str):      # paragraf ringkasan + catatan misi
            texts = [f"{texts[0]} {_t(lang, 'missions', missions=', '.join(f'Misi #{n}' for n in missions))}", *texts[1:]]
        if queued and self.on_supplier_work is not None:
            emit("supplier_contact", lang)
            self.on_supplier_work()
        return {**reset, **_finish(lang, texts, action_id, UI_STATUS[status], status.value)}

    # ------------------------------------------------------------ edges & wiring
    def next_after_parse(self, state) -> str:
        return "auto_resolve" if state["automation_step"] == "resolve" else self.finalize_name

    @staticmethod
    def next_after_resolve(state) -> str:
        return "auto_propose" if state["automation_step"] == "resolved" else "auto_clarify"

    def add_to(self, g) -> None:
        """Adds the PO nodes and edges to the chat `StateGraph`."""
        for name in ("auto_parse", "auto_resolve", "auto_clarify", "auto_propose", "auto_await", "auto_execute"):
            g.add_node(name, getattr(self, name))
        g.add_conditional_edges("auto_parse", self.next_after_parse, ["auto_resolve", self.finalize_name])
        g.add_conditional_edges("auto_resolve", self.next_after_resolve, ["auto_propose", "auto_clarify"])
        g.add_edge("auto_clarify", self.finalize_name)
        g.add_edge("auto_propose", "auto_await")
        g.add_edge("auto_await", "auto_execute")
        g.add_edge("auto_execute", "__end__")


def _finish(lang, texts, action_id, ui_status, db_status=None):
    """Final reply after a card was answered (text blocks + the card's new status)."""
    blocks = [t if isinstance(t, dict) else {"type": "text", "text": t} for t in texts]   # teks atau tabel
    meta = {"intent": "po_automation", "language": lang, "evaluated": False, "sources": [],
            "automation": {"action_id": action_id, "status": db_status or ui_status}}
    update = {action_id: {"status": ui_status}}
    return {"final": {"blocks": blocks, "meta": meta, "action_updates": update},
            "messages": [AIMessage(content="\n".join(t for t in texts if isinstance(t, str)),
                                   additional_kwargs={"blocks": blocks, "meta": meta})]}
