"""Titik sambung `SupplierChatService` -> Hub. Setiap hook menelan error-nya sendiri sehingga
kegagalan Hub tidak pernah menghentikan alur agent PO yang sudah ada."""
import logging

from app.database import SessionLocal

log = logging.getLogger(__name__)


def is_human_mode(supplier_id: int) -> bool:
    """True bila admin mengambil alih thread supplier ini (agent tidak membalas)."""
    try:
        from app.hub.common import is_human
        with SessionLocal() as db:
            return is_human(db, supplier_id)
    except Exception:  # noqa: BLE001
        log.exception("hub hook is_human_mode failed")
        return False


def route_mission_reply(svc, supplier_id: int, chat_id: int, text: str, message_id: int) -> dict | None:
    """Balasan untuk misi Hub yang sedang menunggu; None = lanjutkan ke triage lama."""
    try:
        from app.hub.missions import route_reply
        return route_reply(svc, supplier_id, chat_id, text, message_id)
    except Exception:  # noqa: BLE001
        log.exception("hub hook route_mission_reply failed")
        return None


def store_attachments(svc, chat_id: int, text: str, attachments: list[dict], message_id: int | None) -> dict | None:
    """Foto/dokumen dari supplier -> lampiran thread. None = chat tidak dikenal / gagal (alur lama berlanjut)."""
    try:
        from app.hub.attachments import store_from_telegram
        return store_from_telegram(svc, chat_id, text, attachments, message_id)
    except Exception:  # noqa: BLE001
        log.exception("hub hook store_attachments failed")
        return None


def tick(svc) -> dict | None:
    """Satu putaran dispatcher misi Hub (dipanggil worker)."""
    try:
        from app.hub.missions import tick as hub_tick
        return hub_tick(svc)
    except Exception:  # noqa: BLE001
        log.exception("hub tick failed")
        return None
