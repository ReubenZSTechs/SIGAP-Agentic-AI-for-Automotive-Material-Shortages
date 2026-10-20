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


class SandboxTransport:
    """No network: the `supplier_messages` table is the inbox; replies are injected via the API/Streamlit."""
    name = "sandbox"

    def send(self, chat_id, text, buttons=None):
        return None

    def poll(self, offset, timeout):
        return []

    def ack_button(self, callback_id, text=None):
        return None


class TelegramError(RuntimeError):
    """The Bot API returned ok=false."""


class TelegramTransport:
    """Telegram Bot API over HTTPS (long polling; no webhook needed)."""
    name = "telegram"

    def __init__(self, token: str, client: httpx.Client | None = None):
        self._http = client or httpx.Client(base_url=f"https://api.telegram.org/bot{token}/",
                                            timeout=httpx.Timeout(60.0, connect=10.0))

    def _call(self, method: str, **payload):
        resp = self._http.post(method, json={k: v for k, v in payload.items() if v is not None})
        data = resp.json()
        if not data.get("ok"):
            raise TelegramError(f"{method}: {data.get('description', resp.status_code)}")
        return data["result"]

    def send(self, chat_id, text, buttons=None):
        markup = None
        if buttons:
            markup = {"inline_keyboard": [[{"text": b["label"][:64], "callback_data": b["data"][:64]}]
                                          for b in buttons]}
        result = self._call("sendMessage", chat_id=chat_id, text=text[:4096], reply_markup=markup)
        return result["message_id"]

    def poll(self, offset, timeout):
        updates = self._call("getUpdates", offset=offset, timeout=timeout,
                             allowed_updates=["message", "callback_query"])
        return [self._normalize(u) for u in updates]

    @staticmethod
    def _normalize(u: dict) -> dict:
        if "message" in u:
            m = u["message"]
            return {"update_id": u["update_id"], "kind": "message", "chat_id": m["chat"]["id"],
                    "text": m.get("text") or "", "message_id": m.get("message_id")}
        if "callback_query" in u:
            cq = u["callback_query"]
            return {"update_id": u["update_id"], "kind": "button", "chat_id": cq["message"]["chat"]["id"],
                    "callback_id": cq["id"], "data": cq.get("data") or ""}
        return {"update_id": u["update_id"], "kind": "other"}

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
