from zoneinfo import ZoneInfo
from decimal import Decimal

from typing import Optional

from payment import format_payment_status


MAX_AUDIO_DURATION = 6 * 60 * 60  # seconds; files longer than this are rejected
MIN_PRICE_RUB = Decimal("1.00")  # minimum charge so very short clips stay profitable
SUMMARIZE_THRESHOLD = 300  # seconds; show summarize button only for audio longer than this
RATING_PROMPT = "Оцените качество распознавания"
FEEDBACK_PROMPT = "Расскажите, что пошло не так? Напишите пару слов — это поможет улучшить распознавание."

_OFFER_URL = "https://clear-transcript-bot.ru/user-agreement"
_PRIVACY_URL = "https://clear-transcript-bot.ru/privacy-policy"


def build_payment_text(amount: int, status: str) -> str:
    # The payment link is rendered as a button, so the body carries no URL.
    if status == "CONFIRMED":
        return (
            f"Счёт на {amount} ₽\n"
            f"Статус: {format_payment_status(status)}"
        )

    return (
        f"Счёт на {amount} ₽ создан\n\n"
        "Безопасная оплата через Т‑Банк \\(Тинькофф\\):\n"
        "\\* Банковские карты \\(Visa, MasterCard, Мир\\)\n"
        "\\* Система быстрых платежей \\(СБП\\)\n\n"
        "Данные карты вводятся на стороне банка — бот их не видит\n"
        "После оплаты баланс пополнится автоматически"
    )


def build_topup_text(last_line: str) -> str:
    return (
        "Пополняя баланс, вы соглашаетесь с условиями "
        f"[публичной оферты]({_OFFER_URL}) "
        f"и [политикой обработки персональных данных]({_PRIVACY_URL})\n\n"
        "Безопасная оплата через Т‑Банк \\(Тинькофф\\):\n"
        "\\* Банковские карты \\(Visa, MasterCard, Мир\\)\n"
        "\\* Система быстрых платежей \\(СБП\\)\n\n"
        f"{last_line}"
    )


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


def available_time_by_balance(balance_rub: Decimal) -> str:
    """Return how much audio *balance_rub* covers, rounded down to whole minutes."""
    blocks = int(balance_rub / Decimal("0.15"))
    total_seconds = blocks * 15
    if total_seconds < 60:
        return format_duration(total_seconds)
    hours, r = divmod(total_seconds, 3600)
    minutes = r // 60
    if hours > 0:
        return f"{hours} ч. {minutes} мин."
    return f"{minutes} мин."
