import re

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
