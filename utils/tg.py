import re

from decimal import Decimal


ANCHOR = "/var/lib/telegram-bot-api"

STATUS_EMOJI = {
    "pending": "🕓",
    "running": "⏳",
    "done": "✅",
    "failed": "❌",
    "cancelled": "🚫",
}


def fmt_duration(seconds: int | None) -> str:
    """Format *seconds* to H:MM:SS or M:SS."""
    if not seconds and seconds != 0:
        return "—"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


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
