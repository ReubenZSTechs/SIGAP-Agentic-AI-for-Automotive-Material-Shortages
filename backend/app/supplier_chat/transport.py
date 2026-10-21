"""Message transports: the real Telegram Bot API, or a sandbox that only records to the DB."""
import logging
from typing import Protocol

import httpx

log = logging.getLogger(__name__)

SANDBOX_CHAT_BASE = 10_000_000          # chat id sandbox supplier = BASE + supplier_id
SANDBOX_MANAGER_CHAT_ID = 10_000_000    # chat id sandbox manajer


def sandbox_chat_id(supplier_id: int) -> int:
    return SANDBOX_CHAT_BASE + supplier_id


class Transport(Protocol):
    """What the supplier-chat service needs from a chat channel."""
    name: str

    def send(self, chat_id: int, text: str, buttons: list[dict] | None = None) -> int | None:
        """Sends a message (buttons: [{label, data}], one per row); returns the provider message id."""
        ...

    def poll(self, offset: int | None, timeout: int) -> list[dict]:
        """Normalized updates: {update_id, kind: message|button|other, chat_id, text, message_id, callback_id, data}."""
        ...

    def ack_button(self, callback_id: str, text: str | None = None) -> None:
        ...

    def edit_buttons(self, chat_id: int, message_id: int, buttons: list[dict] | None) -> None:
        """Replaces (None = removes) the inline keyboard of a message sent earlier."""
        ...

    def send_document(self, chat_id: int, filename: str, content: bytes, caption: str | None = None) -> int | None:
        """Sends a file (e.g. the final PO PDF); returns the provider message id."""
        ...


class SandboxTransport:
    """No network: the `supplier_messages` table is the inbox; replies are injected from the Hub (or the API)."""
    name = "sandbox"

    def send(self, chat_id, text, buttons=None):
        return None

    def poll(self, offset, timeout):
        return []

    def ack_button(self, callback_id, text=None):
        return None

    def download(self, file_id):
        return None

    def edit_buttons(self, chat_id, message_id, buttons):
        return None

    def send_document(self, chat_id, filename, content, caption=None):
        return None


class TelegramError(RuntimeError):
    """The Bot API returned ok=false."""


class TelegramTransport:
    """Telegram Bot API over HTTPS (long polling; no webhook needed)."""
    name = "telegram"

    def __init__(self, token: str, client: httpx.Client | None = None):
        self._token = token
        self._http = client or httpx.Client(base_url=f"https://api.telegram.org/bot{token}/",
                                            timeout=httpx.Timeout(60.0, connect=10.0))

    def _call(self, method: str, **payload):
        resp = self._http.post(method, json={k: v for k, v in payload.items() if v is not None})
        data = resp.json()
        if not data.get("ok"):
            raise TelegramError(f"{method}: {data.get('description', resp.status_code)}")
        return data["result"]

    @staticmethod
    def _markup(buttons):
        if not buttons:
            return None
        return {"inline_keyboard": [[{"text": b["label"][:64], "callback_data": b["data"][:64]}] for b in buttons]}

    def send(self, chat_id, text, buttons=None):
        result = self._call("sendMessage", chat_id=chat_id, text=text[:4096], reply_markup=self._markup(buttons))
        return result["message_id"]

    def edit_buttons(self, chat_id, message_id, buttons):
        self._call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
                   reply_markup=self._markup(buttons) or {"inline_keyboard": []})

    def send_document(self, chat_id, filename, content, caption=None):
        resp = self._http.post("sendDocument", data={"chat_id": str(chat_id), **({"caption": caption[:1024]} if caption else {})},
                               files={"document": (filename, content, "application/pdf")})
        data = resp.json()
        if not data.get("ok"):
            raise TelegramError(f"sendDocument: {data.get('description', resp.status_code)}")
        return data["result"]["message_id"]

    def poll(self, offset, timeout):
        updates = self._call("getUpdates", offset=offset, timeout=timeout,
                             allowed_updates=["message", "callback_query"])
        return [self._normalize(u) for u in updates]

    @staticmethod
    def _normalize(u: dict) -> dict:
        if "message" in u:
            m = u["message"]
            out = {"update_id": u["update_id"], "kind": "message", "chat_id": m["chat"]["id"],
                   "text": m.get("text") or m.get("caption") or "", "message_id": m.get("message_id")}
            files = []
            if m.get("photo"):                                    # ukuran terbesar ada di akhir daftar
                p = m["photo"][-1]
                files.append({"file_id": p["file_id"], "name": f"foto_{m.get('message_id')}.jpg",
                              "mime": "image/jpeg", "size": p.get("file_size")})
            if m.get("document"):
                d = m["document"]
                files.append({"file_id": d["file_id"], "name": d.get("file_name") or "dokumen",
                              "mime": d.get("mime_type") or "application/octet-stream", "size": d.get("file_size")})
            if files:
                out["attachments"] = files
            return out
        if "callback_query" in u:
            cq = u["callback_query"]
            return {"update_id": u["update_id"], "kind": "button", "chat_id": cq["message"]["chat"]["id"],
                    "callback_id": cq["id"], "data": cq.get("data") or ""}
        return {"update_id": u["update_id"], "kind": "other"}

    def download(self, file_id: str) -> bytes:
        """Unduh file lampiran (getFile -> /file/bot<token>/<path>); dipakai Agent Hub untuk dokumen."""
        info = self._call("getFile", file_id=file_id)
        resp = self._http.get(f"https://api.telegram.org/file/bot{self._token}/{info['file_path']}")
        resp.raise_for_status()
        return resp.content

    def ack_button(self, callback_id, text=None):
        try:
            self._call("answerCallbackQuery", callback_query_id=callback_id, text=text)
        except (TelegramError, httpx.HTTPError) as e:   # pengakuan tombol tidak kritis
            log.warning("answerCallbackQuery failed: %s", e)


def build_transport(settings) -> Transport:
    if settings.TELEGRAM_MODE == "telegram":
        if not settings.TELEGRAM_BOT_TOKEN:
            raise RuntimeError("TELEGRAM_MODE=telegram membutuhkan TELEGRAM_BOT_TOKEN")
        return TelegramTransport(settings.TELEGRAM_BOT_TOKEN)
    return SandboxTransport()
