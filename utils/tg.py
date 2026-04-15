import re
import logging

from datetime import datetime, timedelta
from decimal import Decimal


EDIT_INTERVAL_SEC = 5


def need_edit(context, item_id: int, now: datetime, cache_key: str = "status_cache") -> bool:
    """Return True if enough time has passed to warrant editing the status message.

    Uses *cache_key* to namespace the throttle cache inside ``context.bot_data``,
    so transcription and summarization tasks don't collide.
    """
    cache = context.bot_data.setdefault(cache_key, {})
    last_ts = cache.get(item_id)
    if not last_ts:
        cache[item_id] = now
        return False
    if now - last_ts < timedelta(seconds=EDIT_INTERVAL_SEC):
        return False
    cache[item_id] = now
    return True


def prune_edit_cache(context, active_ids: set, cache_key: str = "status_cache") -> None:
    """Remove cache entries whose IDs are no longer in *active_ids*.

    Call once per scheduler tick with the current set of running task IDs so
    that orphaned entries (e.g. from a bot restart or unhandled exception) are
    automatically evicted rather than accumulating indefinitely.
    """
    cache = context.bot_data.get(cache_key)
    if not cache:
        return
    for stale_id in [k for k in cache if k not in active_ids]:
        del cache[stale_id]


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


async def safe_edit_message_text(bot, chat_id, message_id, text, reply_markup=None):
    """Safely edit a message text, catching exceptions."""
    if not chat_id or not message_id:
        return
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup
        )
    except Exception:
        logging.exception(
            f"Failed to edit message {message_id} in chat {chat_id}. "
            f"text={repr(text[:30])}"
        )
