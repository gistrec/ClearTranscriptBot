"""Characterization tests for format_payment_status."""
import pytest

from payment import format_payment_status


@pytest.mark.parametrize(
    "status, expected",
    [
        ("NEW", "🕓 не оплачен"),
        ("CONFIRMED", "✅ оплачен"),
        ("AUTHORIZED", "🕓 обрабатывается"),
        ("CANCELED", "🚫 отменён"),
        ("EXPIRED", "⌛ истёк"),
        ("REJECTED", "🚫 отклонён банком"),
        ("AUTH_FAIL", "🚫 ошибка оплаты"),
        ("DEADLINE_EXPIRED", "⌛ истёк срок оплаты"),
    ],
)
def test_known_statuses(status, expected):
    assert format_payment_status(status) == expected


@pytest.mark.parametrize("status", [None, "GARBAGE", "", 123])
def test_unknown_status_falls_back(status):
    assert format_payment_status(status) == "❓ неизвестно"
