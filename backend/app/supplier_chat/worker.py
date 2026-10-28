"""Background worker: Telegram long polling + dispatch of queued conversations + timeouts.

    python -m app.supplier_chat.worker

Run exactly ONE worker per bot token (Telegram allows a single getUpdates consumer). In sandbox
mode it only dispatches queued conversations and handles timeouts.
"""
import logging
import re
import time

from app.chatbot.service import ChatUnavailable
from app.chatbot.tracing import purge_old
from app.config import settings
from app.hub import hooks as hub_hooks
from app.supplier_chat.service import get_supplier_chat_service

log = logging.getLogger("supplier_chat.worker")

TIMEOUT_EVERY_S = 60
PURGE_EVERY_S = 24 * 3600                       # retensi agent_runs (AGENT_TRACE_RETENTION_DAYS)


def run_forever() -> None:
    while True:                                  # tunggu kredensial AI Core (tanpa crash-loop di Docker)
        try:
            svc = get_supplier_chat_service()
            break
        except ChatUnavailable as e:
            log.warning("supplier worker idle: %s", e)
            time.sleep(5)
    cfg = svc.cfg
    live = settings.telegram_live
    log.info("supplier worker started (mode=%s, manager chat=%s)", svc.transport.name, svc.manager_chat_id)
    offset, last_tick, last_purge, backoff = None, 0.0, 0.0, 1
    while True:
        try:
            if live:
                for update in svc.transport.poll(offset, cfg.get("poll_timeout_s", 25)):
                    offset = update["update_id"] + 1
                    try:
                        svc.handle_update(update)
                    except Exception:  # noqa: BLE001  (satu update gagal tidak menghentikan worker)
                        log.exception("update %s failed", update.get("update_id"))
            else:
                time.sleep(cfg.get("idle_sleep_s", 5))
            svc.dispatch_queued()
            hub_hooks.tick(svc)                      # misi Agent Hub (menelan error-nya sendiri)
            if time.monotonic() - last_tick > TIMEOUT_EVERY_S:
                svc.tick_timeouts()
                last_tick = time.monotonic()
            if time.monotonic() - last_purge > PURGE_EVERY_S:
                log.info("purged %s old agent runs", purge_old())
                last_purge = time.monotonic()
            backoff = 1
        except Exception:  # noqa: BLE001
            log.exception("worker loop error; retrying in %ss", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


class RedactBotToken(logging.Filter):
    """Masks Telegram bot tokens (`bot<id>:<secret>`) in every log line, including tracebacks."""
    PATTERN = re.compile(r"bot\d+:[A-Za-z0-9_-]{20,}")

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.PATTERN.sub("bot<redacted>", record.getMessage())
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self.PATTERN.sub("bot<redacted>", record.exc_text)
        return True


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactBotToken())
    # httpx logs every request URL at INFO, and the Telegram Bot API puts the token in the URL.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


if __name__ == "__main__":
    setup_logging()
    run_forever()
