"""Lampiran dari supplier (foto/PDF lewat Telegram atau sandbox).

Disimpan di `hub_documents` dan ditampilkan langsung di thread percakapan (tidak ada tab/validasi Dokumen).
"""
import base64
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import AppError
from app.database import SessionLocal
from app.models import HubDocument, PurchaseOrder, SupplierMessage, SupplierTelegramLink
from app.models.enums import MessageDirection, POStatus
from app.supplier_chat.transport import sandbox_chat_id

log = logging.getLogger(__name__)
MD = MessageDirection
MAX_BYTES = 10 * 1024 * 1024
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
    """Catat pesan IN + simpan file (ditautkan ke PO terbuka bila hanya satu), lalu balas tanda terima."""
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
        db.commit()
    if chat_id is not None:
        svc.deliver([{"chat_id": chat_id, "text": f"Thank you, we have received {names}.",
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


# -------------------------------------------- file --------------------------------------------
def file_content(db: Session, doc_id: int) -> tuple[bytes, str, str]:
    d = db.get(HubDocument, doc_id)
    if d is None:
        raise AppError(404, "Lampiran tidak ditemukan")
    content = db.scalar(select(HubDocument.content).where(HubDocument.id == doc_id))
    if content is None:
        raise AppError(404, "File tidak tersimpan (terlalu besar atau gagal diunduh). Minta ulang ke supplier.")
    return content, d.mime, d.file_name
