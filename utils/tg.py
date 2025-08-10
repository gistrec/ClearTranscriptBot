from decimal import Decimal

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
