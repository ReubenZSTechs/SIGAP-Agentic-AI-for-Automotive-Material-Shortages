"""Dokumen dari supplier (foto/PDF lewat Telegram atau sandbox). Validasi manual tanpa OCR:
admin mengisi nomor, PO, total, dan qty; server membandingkannya dengan data PO."""
import base64
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import AppError
from app.database import SessionLocal
from app.models import HubDocument, HubOutbox, PurchaseOrder, Supplier, SupplierMessage, SupplierTelegramLink
from app.models.enums import MessageDirection, POStatus
from app.models.hub import DocumentStatus
from app.hub import common as C
from app.supplier_chat.transport import sandbox_chat_id
from configs.tools import po_actions as A

log = logging.getLogger(__name__)
MD = MessageDirection
MAX_BYTES = 10 * 1024 * 1024
DOC_TYPES = {"INVOICE": "invoice", "DELIVERY_NOTE": "surat jalan", "TAX_INVOICE": "faktur pajak", "OTHER": "dokumen"}
OPEN_PO = (POStatus.ISSUED, POStatus.PARTIALLY_RECEIVED, POStatus.RECEIVED)


def _kind(mime: str, name: str) -> str:
    if mime.startswith("image/"):
        return "image"
    return "pdf" if mime == "application/pdf" or name.lower().endswith(".pdf") else "file"


def _guess_po(db: Session, supplier_id: int) -> int | None:
    ids = list(db.scalars(select(PurchaseOrder.id).where(PurchaseOrder.supplier_id == supplier_id,
                                                         PurchaseOrder.status.in_(OPEN_PO)).limit(2)))
    return ids[0] if len(ids) == 1 else None


def store(svc, supplier_id: int, chat_id: int | None, caption: str, files: list[dict],
          telegram_message_id: int | None = None) -> dict:
    """Catat pesan IN + simpan file + tautkan ke misi DOC_REQUEST yang menunggu, lalu balas tanda terima."""
    from app.hub import missions
    names = ", ".join(f["name"] for f in files)
    with SessionLocal() as db:
        msg = SupplierMessage(supplier_id=supplier_id, chat_id=chat_id, direction=MD.IN,
                              text=caption or f"[lampiran] {names}", telegram_message_id=telegram_message_id)
        db.add(msg)
        db.flush()
        po_id = _guess_po(db, supplier_id)
        ids = []
        for f in files:
            content = f.get("content")
            if content is not None and len(content) > MAX_BYTES:
                content, note = None, "File lebih dari 10 MB; tidak disimpan."
            else:
                note = None
            d = HubDocument(supplier_id=supplier_id, message_id=msg.id, kind=_kind(f["mime"], f["name"]),
                            file_name=f["name"][:160], mime=f["mime"][:80], size=f.get("size") or len(content or b""),
                            content=content, telegram_file_id=f.get("file_id"), po_id=po_id, note=note)
            db.add(d)
            db.flush()
            ids.append(d.id)
        m = missions.attach_documents(db, supplier_id, ids)
        if m is not None:
            for d in db.scalars(select(HubDocument).where(HubDocument.id.in_(ids))):
                d.mission_id, d.po_id = m.id, m.po_id or d.po_id
        db.commit()
    if chat_id is not None:
        svc.deliver([{"chat_id": chat_id, "text": f"Terima kasih, {names} kami terima dan akan diperiksa tim kami.",
                      "direction": MD.OUT, "supplier_id": supplier_id,
                      "agent_output": {"source": "hub_template", "kind": "document_ack"}}])
    return {"handled": True, "documents": ids}


def store_from_telegram(svc, chat_id: int, text: str, attachments: list[dict], message_id: int | None) -> dict | None:
    with SessionLocal() as db:
        link = db.scalar(select(SupplierTelegramLink).where(SupplierTelegramLink.chat_id == chat_id))
        if link is None:
            return None
        supplier_id = link.supplier_id
    files = []
    for a in attachments:
        content = None
        download = getattr(svc.transport, "download", None)
        if download and a.get("file_id") and (a.get("size") or 0) <= MAX_BYTES:
            try:
                content = download(a["file_id"])
            except Exception:  # noqa: BLE001  (file tetap dicatat; bisa diminta ulang)
                log.exception("download %s failed", a.get("file_id"))
        files.append({"name": a.get("name") or "lampiran", "mime": a.get("mime") or "application/octet-stream",
                      "size": a.get("size"), "file_id": a.get("file_id"), "content": content})
    return store(svc, supplier_id, chat_id, text, files, message_id)


def sandbox_upload(svc, body: dict) -> dict:
    if settings.TELEGRAM_MODE != "sandbox":
        raise AppError(409, "Endpoint sandbox hanya aktif bila TELEGRAM_MODE=sandbox")
    supplier_id = int(body["supplier_id"])
    with SessionLocal() as db:
        link = db.scalar(select(SupplierTelegramLink).where(SupplierTelegramLink.supplier_id == supplier_id))
        if link is None or link.chat_id != sandbox_chat_id(supplier_id):
            raise AppError(409, "Supplier belum ditautkan ke chat sandbox")
    try:
        content = base64.b64decode(body["content_base64"], validate=True)
    except (KeyError, ValueError) as e:
        raise AppError(422, "content_base64 tidak valid") from e
    if len(content) > MAX_BYTES:
        raise AppError(413, "File maksimal 10 MB")
    files = [{"name": body.get("file_name") or "lampiran", "mime": body.get("mime") or "application/octet-stream",
              "size": len(content), "content": content}]
    return store(svc, supplier_id, sandbox_chat_id(supplier_id), (body.get("caption") or "").strip(), files)


# -------------------------------------------- views --------------------------------------------
def compare(db: Session, d: HubDocument) -> list[dict]:
    """Isian manual admin vs PO. `match=None` = tidak dibandingkan."""
    f = d.fields or {}
    po = db.get(PurchaseOrder, d.po_id) if d.po_id else None
    tol = C.threshold(db, "invoice_tolerance_rp")
    rows = [{"key": "po", "label": "Nomor PO tertulis", "doc": f.get("po_number"), "ref": po.po_number if po else None,
             "unit": "text", "critical": True},
            {"key": "number", "label": "Nomor dokumen", "doc": d.number, "ref": None, "unit": "text"},
            {"key": "date", "label": "Tanggal dokumen", "doc": f.get("doc_date"), "ref": None, "unit": "date"}]
    if d.doc_type in ("INVOICE", "TAX_INVOICE"):
        rows.append({"key": "total", "label": "Total", "doc": f.get("total"), "ref": po.total_amount if po else None,
                     "unit": "Rp", "critical": True, "tolerance": tol})
    if po is not None:
        qty = {str(k): v for k, v in (f.get("qty") or {}).items()}
        for it in po.items:
            if str(it.material_id) in qty or d.doc_type == "DELIVERY_NOTE":
                rows.append({"key": f"qty:{it.material_id}", "label": f"{it.sku} {it.name}", "doc": qty.get(str(it.material_id)),
                             "ref": it.qty_ordered, "unit": "qty", "material_id": it.material_id})
    for r in rows:
        r.setdefault("critical", False)
        if r["ref"] is None or r["doc"] in (None, ""):
            r["match"] = None
        elif r["unit"] == "Rp":
            r["match"] = abs(float(r["doc"]) - float(r["ref"])) <= (r.get("tolerance") or 0)
        elif r["unit"] == "qty":
            r["match"] = float(r["doc"]) == float(r["ref"])
        else:
            r["match"] = str(r["doc"]).strip().upper() == str(r["ref"]).strip().upper()
    return rows


def doc_view(db: Session, d: HubDocument, full: bool = False) -> dict:
    rows = compare(db, d)
    po = db.get(PurchaseOrder, d.po_id) if d.po_id else None
    sup = db.get(Supplier, d.supplier_id)
    out = {"id": d.id, "kind": d.kind, "file_name": d.file_name, "mime": d.mime, "size": d.size, "has_file": d.content is not None,
           "doc_type": d.doc_type, "number": d.number, "supplier": {"id": sup.id, "name": sup.name}, "thread_id": sup.id,
           "po_id": d.po_id, "po_number": po.po_number if po else None, "mission_id": d.mission_id,
           "status": d.status.value, "received_at": C.iso(d.received_at), "decided_by": d.decided_by,
           "decided_at": C.iso(d.decided_at), "note": d.note,
           "mismatches": sum(1 for r in rows if r["match"] is False),
           "critical_mismatches": sum(1 for r in rows if r["match"] is False and r["critical"]),
           "filled": bool(d.doc_type and d.po_id)}
    if full:
        out.update({"fields": d.fields or {}, "compare": rows,
                    "po": A.po_snapshot(po) if po else None,
                    "po_choices": [{"id": p.id, "po_number": p.po_number, "status": p.status.value} for p in db.scalars(
                        select(PurchaseOrder).where(PurchaseOrder.supplier_id == d.supplier_id)
                        .order_by(PurchaseOrder.id.desc()).limit(20))]})
    return out


def list_documents(db: Session) -> list[dict]:
    return [doc_view(db, d) for d in db.scalars(select(HubDocument).order_by(HubDocument.id.desc()).limit(200))]


def _doc(db: Session, doc_id: int) -> HubDocument:
    d = db.get(HubDocument, doc_id)
    if d is None:
        raise AppError(404, "Dokumen tidak ditemukan")
    return d


def get_document(db: Session, doc_id: int) -> dict:
    return doc_view(db, _doc(db, doc_id), full=True)


def file_content(db: Session, doc_id: int) -> tuple[bytes, str, str]:
    d = _doc(db, doc_id)
    content = db.scalar(select(HubDocument.content).where(HubDocument.id == doc_id))
    if content is None:
        raise AppError(404, "File tidak tersimpan (terlalu besar atau gagal diunduh). Minta ulang ke supplier.")
    return content, d.mime, d.file_name


def update_fields(db: Session, doc_id: int, body: dict, actor: str) -> dict:
    d = _doc(db, doc_id)
    if d.status != DocumentStatus.NEEDS_REVIEW:
        raise AppError(409, "Dokumen sudah divalidasi")
    if body.get("doc_type") is not None:
        if body["doc_type"] not in DOC_TYPES:
            raise AppError(422, "Jenis dokumen tidak dikenal")
        d.doc_type = body["doc_type"]
    if "number" in body:
        d.number = (body.get("number") or "").strip()[:60] or None
    if "po_id" in body:
        if body["po_id"] is not None:
            po = db.get(PurchaseOrder, int(body["po_id"]))
            if po is None or po.supplier_id != d.supplier_id:
                raise AppError(422, "PO harus milik supplier pengirim dokumen")
        d.po_id = body.get("po_id")
    fields = dict(d.fields or {})
    for k in ("po_number", "doc_date", "total", "qty"):
        if k in body:
            fields[k] = body[k]
    d.fields = fields
    C.audit(db, actor, "fill_document", "document", d.id)
    db.commit()
    return doc_view(db, d, full=True)


def archive(db: Session, doc_id: int, actor: str, confirm_mismatch: bool) -> dict:
    d = _doc(db, doc_id)
    if d.status != DocumentStatus.NEEDS_REVIEW:
        raise AppError(409, "Dokumen sudah divalidasi")
    if not (d.doc_type and d.po_id):
        raise AppError(422, "Isi jenis dokumen dan PO terkait sebelum mengarsipkan")
    critical = [r["label"] for r in compare(db, d) if r["match"] is False and r["critical"]]
    if critical and not confirm_mismatch:
        raise AppError(409, f"Kolom kunci berbeda: {', '.join(critical)}. Konfirmasi selisih dulu.", {"critical": critical})
    d.status, d.decided_by, d.decided_at = DocumentStatus.ARCHIVED, actor, A.now()
    d.note = f"Diarsipkan dengan selisih dikonfirmasi: {', '.join(critical)}"[:300] if critical else d.note
    C.audit(db, actor, "archive_document", "document", d.id, mismatches=critical)
    db.commit()
    return doc_view(db, d, full=True)


def request_again(svc, doc_id: int, actor: str, reason: str) -> dict:
    reason = reason.strip()
    if len(reason) < 3:
        raise AppError(422, "Alasan wajib diisi (min. 3 karakter)")
    sends = []
    with SessionLocal() as db:
        d = _doc(db, doc_id)
        if d.status != DocumentStatus.NEEDS_REVIEW:
            raise AppError(409, "Dokumen sudah divalidasi")
        sup = db.get(Supplier, d.supplier_id)
        label = DOC_TYPES.get(d.doc_type or "OTHER")
        text = (f"Selamat {C.greeting()} {C.contact_name(sup)}, mohon kirim ulang {label} "
                f"{d.number or d.file_name}. {reason} Terima kasih.")
        review = C.outbound(db, "DOC_REQUEST") == "REVIEW" or C.is_paused(db)
        if review:
            db.add(HubOutbox(supplier_id=d.supplier_id, kind="document", text=text,
                             review_reason="Permintaan dokumen diatur \"Draf dulu\"" if not C.is_paused(db) else "Agent dijeda"))
        else:
            chat_id = svc.supplier_chat_id(db, d.supplier_id)
            if chat_id is None:
                raise AppError(409, "Supplier belum terhubung ke Telegram")
            sends.append({"chat_id": chat_id, "text": text, "direction": MD.OUT, "supplier_id": d.supplier_id,
                          "agent_output": {"source": "hub_template", "kind": "document_request", "reviewed_by": actor}})
        d.status, d.decided_by, d.decided_at, d.note = DocumentStatus.REREQUESTED, actor, A.now(), reason[:300]
        C.audit(db, actor, "rerequest_document", "document", d.id, reason=reason)
        db.commit()
        view = doc_view(db, d, full=True)
    svc.deliver(sends)
    return {**view, "drafted": review}
