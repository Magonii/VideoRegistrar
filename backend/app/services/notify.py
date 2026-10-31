import logging

import httpx

from ..config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

log = logging.getLogger("notify")


def send_notification(text: str) -> bool:
    """Telegram, если заданы TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID; иначе только лог."""
    log.warning("ALERT: %s", text)
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return False
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as exc:  # уведомление не должно ронять движок алертов
        log.error("Telegram notification failed: %s", exc)
        return False
