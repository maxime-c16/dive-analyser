"""Best-effort Telegram message to the operator chat (funnel watchdog bot).

The bot token is a secret: it is part of the request URL, so neither the URL
nor exception text is ever logged.
"""
import logging

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)
_TIMEOUT_SECONDS = 10


def configured() -> bool:
    settings = get_settings()
    return bool(settings.sessions_telegram_bot_token.strip() and settings.sessions_telegram_chat_id.strip())


def send(text: str) -> bool:
    if not configured():
        return False
    settings = get_settings()
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{settings.sessions_telegram_bot_token.strip()}/sendMessage",
            data={"chat_id": settings.sessions_telegram_chat_id.strip(), "text": text[:4000],
                  "disable_web_page_preview": "true"},
            timeout=_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        logger.warning("telegram send failed (%s)", type(exc).__name__)
        return False
    if response.status_code != 200:
        logger.warning("telegram send failed (status %s)", response.status_code)
        return False
    return True
