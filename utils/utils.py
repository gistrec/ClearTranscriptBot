from zoneinfo import ZoneInfo
from decimal import Decimal
from math import ceil


MoscowTimezone = ZoneInfo("Europe/Moscow")

USD_TO_RUB = Decimal("80")


def format_duration(duration_sec: int) -> str:
    """Format duration in seconds as:
    * '{h} ч. {m} мин. {s} сек.'
    * '{m} мин. {s} сек.'
    * '{s} сек.'
    """
    total = int(duration_sec or 0)
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


def cost_replicate_rub(predict_time_sec: float) -> Decimal:
    """
    Стоимость предсказания Replicate в рублях.

    Тарификация: $0.000975 за секунду (Nvidia L40S GPU), конвертация по курсу 80 ₽/$.
    """
    usd = Decimal(str(predict_time_sec)) * Decimal("0.000975")
    return (usd * USD_TO_RUB).quantize(Decimal("0.01"))


def cost_yc_async_rub(duration_s: float, channels: int = 1, deferred: bool = False) -> str:
    """
    Стоимость асинхронного распознавания Yandex SpeechKit в рублях.

    Правила биллинга:
      - длительность округляется вверх до целых секунд;
      - число каналов округляется вверх до чётного;
      - минимум 15 секунд на КАЖДУЮ пару каналов (2 канала);
      - тарификация ведётся за блоки по 15 секунд ДВУХКАНАЛЬНОГО аудио.

    По умолчанию:
      - обычный async:     0.15 ₽ за 15 секунд;
      - отложенный режим:  0.0375 ₽ за 15 секунд.

    Возвращает строку с ценой в рублях (с 2 знаками после запятой).
    """
    # Округляем секунды и каналы по правилам
    seconds_rounded = ceil(max(0.0, duration_s))
    ch_even = max(1, channels)
    if ch_even % 2 == 1:
        ch_even += 1
    pairs = ch_even // 2

    # Минимум 15 секунд на пару каналов
    seconds_per_pair = max(seconds_rounded, 15)

    # Считаем 15-секундные блоки двухканального аудио
    total_seconds = seconds_per_pair * pairs
    blocks_15s = (total_seconds + 14) // 15  # ceil(total_seconds / 15)

    cost_rub = blocks_15s * (0.0375 if deferred else 0.15)
    return f"{cost_rub:.2f}"
