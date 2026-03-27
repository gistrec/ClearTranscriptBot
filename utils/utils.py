from zoneinfo import ZoneInfo
from decimal import Decimal

from typing import Optional


MoscowTimezone = ZoneInfo("Europe/Moscow")


def format_duration(duration_sec: Optional[int]) -> str:
    """Format duration in seconds as:
    * '{h} ч. {m} мин. {s} сек.'
    * '{m} мин. {s} сек.'
    * '{s} сек.'
    """
    total = int(duration_sec or 0)
    if total < 1:
        return "<1 сек."

    hours, r = divmod(total, 3600)
    minutes, seconds = divmod(r, 60)

    if hours > 0:
        return f"{hours} ч. {minutes} мин. {seconds} сек."
    if minutes > 0:
        return f"{minutes} мин. {seconds} сек."
    return f"{seconds} сек."


def available_time_by_balance(
    balance_rub: Decimal, channels: int = 1, deferred: bool = False
) -> str:
    """Return minutes and seconds that can be transcribed for *balance_rub*."""
    price_per_block = Decimal("0.0375") if deferred else Decimal("0.15")
    blocks = int(balance_rub / price_per_block)
    total_seconds = blocks * 15
    return format_duration(total_seconds)
