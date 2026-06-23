import re

from datetime import datetime, timedelta
from decimal import Decimal

from database.models import (
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_REJECTED,
    STATUS_CANCELLED,
)


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
    STATUS_PENDING: "🕓",
    STATUS_RUNNING: "⏳",
    STATUS_COMPLETED: "✅",
    STATUS_FAILED: "❌",
    STATUS_REJECTED: "↩️",
    STATUS_CANCELLED: "🚫",
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


def truncate_filename(name: str, max_bytes: int = 200) -> str:
    """Truncate *name* to *max_bytes* UTF-8 bytes, keeping the extension.

    Linux NAME_MAX is 255 bytes per path component; default budget leaves
    room for suffixes like ``.progress`` added downstream.
    """
    if len(name.encode("utf-8")) <= max_bytes:
        return name

    from pathlib import Path

    suffix = Path(name).suffix
    stem = name[: -len(suffix)] if suffix else name

    suffix_bytes = suffix.encode("utf-8")
    budget = max_bytes - len(suffix_bytes)
    if budget <= 0:
        return name.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore") or "audio"

    truncated_stem = stem.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
    return (truncated_stem + suffix) if truncated_stem else ("audio" + suffix)


def is_supported_mime(mime: str) -> bool:
    return mime.startswith("audio/") or mime.startswith("video/")


