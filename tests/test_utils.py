"""Characterization tests for pure helpers in utils.utils.

These lock the current observable behavior so the planned handler refactor
can't silently change user-facing text or price math.
"""
from decimal import Decimal

import pytest

from utils.utils import (
    available_time_by_balance,
    build_payment_text,
    build_topup_text,
    format_duration,
)


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (None, "<1 сек."),
        (0, "<1 сек."),
        (1, "1 сек."),
        (59, "59 сек."),
        (75, "1 мин. 15 сек."),
        (3600, "1 ч. 0 мин. 0 сек."),
        (4995, "1 ч. 23 мин. 15 сек."),
    ],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


@pytest.mark.parametrize(
    "balance, expected",
    [
        (Decimal("0"), "<1 сек."),
        (Decimal("0.15"), "15 сек."),
        (Decimal("1"), "1 мин."),
        (Decimal("50"), "1 ч. 23 мин."),
    ],
)
def test_available_time_by_balance(balance, expected):
    assert available_time_by_balance(balance) == expected


def test_build_payment_text_confirmed():
    assert build_payment_text(250, "CONFIRMED") == (
        "Счёт на 250 ₽\n"
        "Статус: ✅ оплачен"
    )


def test_build_payment_text_pending_is_markdown_v2_escaped():
    expected = (
        "Счёт на 250 ₽ создан\n\n"
        "Безопасная оплата через Т‑Банк \\(Тинькофф\\):\n"
        "\\* Банковские карты \\(Visa, MasterCard, Мир\\)\n"
        "\\* Система быстрых платежей \\(СБП\\)\n\n"
        "Данные карты вводятся на стороне банка — бот их не видит\n"
        "После оплаты баланс пополнится автоматически"
    )
    assert build_payment_text(250, "NEW") == expected


def test_build_payment_text_pending_branch_is_status_agnostic():
    # Any non-CONFIRMED status renders the same "счёт создан" body.
    assert build_payment_text(100, "NEW") == build_payment_text(100, "EXPIRED")


def test_build_topup_text_locks_offer_links_and_escaping():
    expected = (
        "Пополняя баланс, вы соглашаетесь с условиями "
        "[публичной оферты](https://clear-transcript-bot.ru/user-agreement) "
        "и [политикой обработки персональных данных]"
        "(https://clear-transcript-bot.ru/privacy-policy)\n\n"
        "Безопасная оплата через Т‑Банк \\(Тинькофф\\):\n"
        "\\* Банковские карты \\(Visa, MasterCard, Мир\\)\n"
        "\\* Система быстрых платежей \\(СБП\\)\n\n"
        "Выберите сумму пополнения"
    )
    assert build_topup_text("Выберите сумму пополнения") == expected


def test_build_topup_text_appends_last_line():
    assert build_topup_text("Сумма пополнения: 500 ₽").endswith(
        "\n\nСумма пополнения: 500 ₽"
    )
