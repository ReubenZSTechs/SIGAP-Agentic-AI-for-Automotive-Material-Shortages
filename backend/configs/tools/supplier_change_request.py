"""Supplier revision requests: validate the proposed changes, offer the manager options, execute the choice."""
import re
from datetime import date

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import POChangeRequest, PurchaseOrder, SupplierConversation
from app.models.enums import ConversationPurpose, POStatus
from app.services import po_service
from configs.tools.po_common import _FIELD, CRS, CS, SCS, _has_receipts, _iso, now, po_snapshot
from configs.tools.po_execute import _check_snapshot, _get_po, cancel_po, confirmation, create_and_issue_po
from configs.tools.po_sourcing import _group_by_supplier, _line, active_links, pick_supplier
from configs.tools.supplier_conversation import (
    _add_revision,
    _match_line,
    close_conversation,
    note_action,
    queue_conversation,
    revisions,
)

# ---------------------------------- supplier revisions ----------------------------------

def parse_rupiah(raw: str) -> int:
    """Supplier-written Rupiah amount -> integer Rupiah; raises ValueError when it is not a price.

    Examples the agent may pass on: "12500", "12.500", "Rp 12.500,00", "12500.00", "12,500".
    """
    s = re.sub(r"(?i)^\s*rp\.?|\s", "", str(raw))
    if not re.fullmatch(r"\d[\d.,]*", s) or s[-1] in ".,":
        raise ValueError("price is not a number")
    # Separator terakhir diikuti tepat dua digit = sen ("12.500,00", "12500.00"); separator lain = ribuan
    # ("12.500", "12,500", "1.250.000"). Rupiah dibulatkan ke rupiah penuh.
    whole, cents = s, "0"
    m = re.fullmatch(r"(.*\d)[.,](\d{2})", s)
    if m:
        whole, cents = m.groups()
    return int(re.sub(r"[.,]", "", whole)) + (1 if int(cents) >= 50 else 0)


def _parse_change(field: str, raw: str, po: PurchaseOrder):
    raw = str(raw).strip()
    if field == "qty_ordered":
        value = float(raw.replace(",", "."))
        if value <= 0:
            raise ValueError("qty must be > 0")
        return value
    if field == "unit_price":
        return parse_rupiah(raw)
    value = date.fromisoformat(raw)
    if value < po.po_date:
        raise ValueError("date is before the PO date")
    return value.isoformat()


def find_alternative_suppliers(db: Session, po: PurchaseOrder) -> list[dict] | None:
    """Other suppliers for every open line (via `pick_supplier`), grouped per supplier; None if any line has none."""
    lines = []
    for it in po.items:
        qty = it.qty_ordered - it.qty_received
        link = pick_supplier(active_links(db, it.material_id), qty, exclude_supplier_id=po.supplier_id)
        if link is None:
            return None
        lines.append((link, _line(link, {"material_id": it.material_id, "sku": it.sku, "name": it.name, "uom": it.uom},
                                  qty, _iso(it.needed_by_date))))
    return _group_by_supplier(db, lines) if lines else None


def open_change_request(db: Session, conv: SupplierConversation, proposed: list[dict], supplier_message: str,
                        max_revision_rounds: int) -> POChangeRequest | None:
    """Validates a supplier's revision and stores it with the options the manager may choose.

    Options are computed here, never by the LLM: abort (always), approve_change (every change
    valid, PO still ISSUED without receipts, revision rounds left), resource (alternatives exist).
    Returns None when the supplier proposed nothing concrete.
    """
    if not proposed:
        return None
    po = _get_po(db, conv.po_id)
    valid, invalid = [], []
    for pc in proposed:
        line, field = _match_line(po, pc.get("material_ref")), _FIELD.get(pc.get("field"))
        if line is None or field is None:
            invalid.append({**pc, "error": "not a line of this PO"})
            continue
        try:
            new = _parse_change(field, pc.get("new_value"), po)
        except ValueError as e:
            invalid.append({**pc, "error": str(e)})
            continue
        old = _iso(getattr(line, field))
        if new != old:
            valid.append({"po_item_id": line.id, "sku": line.sku, "name": line.name, "uom": line.uom,
                          "field": field, "old": old, "new": new, "reason": pc.get("reason")})
    conf = confirmation(db, po.id)
    snap = po_snapshot(po)
    options = [{"key": "abort", "label": "Batalkan PO",
                "effect": f"{po.po_number} dibatalkan (status Dibatalkan, data PO tetap tersimpan; stok on-order "
                          "dikembalikan) dan supplier diberi tahu."}]
    if valid and not invalid and po.status == POStatus.ISSUED and not _has_receipts(po) \
            and conf.revision_round < max_revision_rounds:
        changes = {(c["po_item_id"], c["field"]): c["new"] for c in valid}
        after = []
        for it in snap["items"]:
            line = {**it, **{f: changes[(it["po_item_id"], f)] for f in _FIELD.values() if (it["po_item_id"], f) in changes}}
            line["line_total"] = round(line["qty_ordered"] * line["unit_price"])
            after.append(line)
        options.append({"key": "approve_change", "label": "Setujui perubahan",
                        "effect": f"{po.po_number} direvisi; supplier menerima daftar perubahannya untuk dikonfirmasi.",
                        "items_after": after, "total_before": po.total_amount,
                        "total_after": sum(i["line_total"] for i in after)})
    alternatives = find_alternative_suppliers(db, po)
    if alternatives:
        names = ", ".join(g["supplier_name"] for g in alternatives)
        options.append({"key": "resource", "label": "Pesan ke supplier lain",
                        "effect": f"PO baru diterbitkan ke {names}; {po.po_number} dibatalkan (tetap tersimpan) dan "
                                  "supplier lama diberi tahu.",
                        "purchase_orders": alternatives,
                        "grand_total": sum(g["total_amount"] for g in alternatives)})
    cr = POChangeRequest(po_id=po.id, po_number=po.po_number, po_snapshot=snap, conversation_id=conv.id,
                         supplier_id=po.supplier_id, proposed_changes=valid, invalid_changes=invalid,
                         supplier_message=supplier_message, options=options, status=CRS.PENDING_MANAGER)
    db.add(cr)
    db.flush()
    conf.status = SCS.REVISION_PENDING
    conv.status = CS.REVISION_REQUESTED
    conv.outcome = {**(conv.outcome or {}), "change_request_id": cr.id}
    return cr


def apply_change_request(db: Session, cr: POChangeRequest, choice: str, actor: str) -> dict:
    """Executes the manager's choice. Returns ids of new POs / queued conversations and supplier notices.

    Outbound Telegram messages are NOT sent here; the caller sends them after the commit.
    """
    if cr.status not in (CRS.PENDING_MANAGER, CRS.AWAITING_MANAGER_CONFIRM):
        raise AppError(409, f"Permintaan revisi #{cr.id} sudah diproses ({cr.status.value})")
    option = next((o for o in cr.options if o["key"] == choice), None)
    if option is None:
        raise AppError(422, f"Opsi '{choice}' tidak tersedia untuk permintaan revisi #{cr.id}")
    po = _get_po(db, cr.po_id)
    _check_snapshot(po, cr.po_snapshot)
    conv = db.get(SupplierConversation, cr.conversation_id) if cr.conversation_id else None
    action_id = conv.automation_action_id if conv else None
    result = {"choice": choice, "po_number": po.po_number, "new_pos": [], "queued_conversations": [], "notices": []}

    if choice == "approve_change":
        po_service.apply_supplier_revision(db, po, [{"po_item_id": c["po_item_id"], "field": c["field"],
                                                     "new": c["new"]} for c in cr.proposed_changes])
        if not revisions(db, po.id):                          # PO dikirim sebelum riwayat versi ada
            _add_revision(db, po, cr.po_snapshot, [], None)
        rev = _add_revision(db, po, po_snapshot(po), cr.proposed_changes, actor, change_request_id=cr.id)
        result["revision"] = {"id": rev.id, "version": rev.version}
        conf = confirmation(db, po.id)
        conf.revision_round += 1
        conf.status = SCS.PENDING
        if conv:
            close_conversation(conv, CS.CLOSED, change_request_id=cr.id, result="change_approved")
        new_conv = queue_conversation(db, po, ConversationPurpose.REVISION_CONFIRM, action_id, change_request_id=cr.id)
        collected = (conv.outcome or {}).get("collected") if conv else None
        if collected:                                       # mis. tanggal kirim yang sudah disebut supplier
            new_conv.outcome = {"collected": collected}
        result["queued_conversations"].append(new_conv.id)
        result["total_after"] = po.total_amount
        cr.status = CRS.CHANGE_APPROVED
    elif choice == "abort":
        if conv:
            close_conversation(conv, CS.CLOSED, change_request_id=cr.id, result="aborted")
        snap = cancel_po(db, po.id, "manajer menolak permintaan revisi supplier")
        result["notices"].append({"supplier_id": cr.supplier_id, "conversation_id": cr.conversation_id, "snapshot": snap})
        note_action(db, action_id, supplier_outcome=f"{snap['po_number']} dibatalkan manajer setelah permintaan revisi")
        cr.status = CRS.ABORTED
    else:   # resource: terbitkan PO pengganti DULU, baru hapus PO lama
        for group in option["purchase_orders"]:
            new = create_and_issue_po(db, group, actor, notes=f"Pengganti {po.po_number} (revisi supplier tidak diterima)")
            new_conv = queue_conversation(db, new, ConversationPurpose.CONFIRM_ORDER, action_id)
            result["new_pos"].append({"id": new.id, "po_number": new.po_number, "supplier_name": new.supplier_name,
                                      "total_amount": new.total_amount})
            result["queued_conversations"].append(new_conv.id)
        if conv:
            close_conversation(conv, CS.CLOSED, change_request_id=cr.id, result="resourced")
        snap = cancel_po(db, po.id, "dialihkan ke " + ", ".join(p["po_number"] for p in result["new_pos"]))
        result["notices"].append({"supplier_id": cr.supplier_id, "conversation_id": cr.conversation_id, "snapshot": snap})
        note_action(db, action_id, supplier_outcome=f"{snap['po_number']} dialihkan ke "
                                                    + ", ".join(p["po_number"] for p in result["new_pos"]))
        cr.status = CRS.RESOURCED
    cr.manager_choice, cr.pending_choice, cr.decided_at = choice, None, now()
    cr.result = {k: v for k, v in result.items() if k != "notices"}
    db.flush()
    return result
