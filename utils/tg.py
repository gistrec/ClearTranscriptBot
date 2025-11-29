import os
import re
import logging
import sentry_sdk

from decimal import Decimal


ANCHOR = "/var/lib/telegram-bot-api"

STATUS_EMOJI = {
    "pending": "🕓",
    "running": "⏳",
    "completed": "✅",
    "failed": "❌",
    "cancelled": "🚫",
}


def fmt_price(value) -> str:
    """Format price value in rubles."""
    if value is None:
        return "—"
    if isinstance(value, Decimal):
        return f"{value:.2f} ₽"
    return f"{float(value):.2f} ₽"


def extract_local_path(file_path: str) -> str:
    m = re.search(rf"({re.escape(ANCHOR)}/.+)$", file_path)
    if not m:
        raise RuntimeError(f"Не удалось вытащить локальный путь из: {file_path!r}")
    return m.group(1)


def sanitize_filename(name: str) -> str:
    """Return a safe file name containing Latin/Cyrillic letters, digits and separators."""

    sanitized = re.sub(r"[^0-9A-Za-zА-Яа-яЁё._-]", "_", name)
    sanitized = re.sub(r"_+", "_", sanitized)
    sanitized = sanitized.strip("._")
    return sanitized or "audio"


def is_supported_mime(mime: str) -> bool:
    return mime.startswith("audio/") or mime.startswith("video/")


async def safe_edit_message_text(bot, chat_id, message_id, text):
    """Safely edit a message text, catching exceptions."""
    if not chat_id or not message_id:
        return
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
    except Exception as e:
        logging.error(f"Failed to edit message {message_id} in chat {chat_id}: {e}")

        if os.getenv("ENABLE_SENTRY") == "1":
            sentry_sdk.capture_exception(e)
