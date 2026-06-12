import hashlib
import ssl
from pathlib import Path

import certifi
import httpx

import config

from utils.sentry import sentry_span


# Т-Банк переводит эквайринг на сертификаты Минцифры, которых нет в certifi,
# поэтому доверяем бандлу certifi плюс корневому сертификату Минцифры.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
_SSL_CONTEXT.load_verify_locations(
    Path(__file__).parent / "certs" / "russian_trusted_root_ca.pem"
)

TERMINAL_KEY = config.TERMINAL_KEY
TERMINAL_PASSWORD = config.TERMINAL_PASSWORD
ENV = config.TERMINAL_ENV

BASE_URL = (
    "https://securepay.tinkoff.ru/v2"
    if ENV == "prod"
    else "https://rest-api-test.tinkoff.ru/v2"
)
# Список тестовых карт Тинькофф:
# https://developer.tbank.ru/eacq/intro/errors/test
#
# 4300 0000 0000 0777
# 12/30
# 111


PAYMENT_STATUSES = {
    "NEW": "не оплачен",
    "CONFIRMED": "оплачен",
    "AUTHORIZED": "обрабатывается",
    "CANCELED": "отменён",
    "EXPIRED": "истёк",
    "REJECTED": "отклонён банком",
    "AUTH_FAIL": "ошибка оплаты",
    "DEADLINE_EXPIRED": "истёк срок оплаты",
}

PAYMENT_STATUS_EMOJI = {
    "NEW": "🕓",
    "CONFIRMED": "✅",
    "AUTHORIZED": "🕓",
    "CANCELED": "🚫",
    "EXPIRED": "⌛",
    "REJECTED": "🚫",
    "AUTH_FAIL": "🚫",
    "DEADLINE_EXPIRED": "⌛",
}


def format_payment_status(status: str | None) -> str:
    """Return payment status text with emoji for user-facing messages."""
    if isinstance(status, str) and status in PAYMENT_STATUSES:
        return f"{PAYMENT_STATUS_EMOJI[status]} {PAYMENT_STATUSES[status]}"
    return "❓ неизвестно"


def _generate_token(params: dict) -> str:
    data = params.copy()
    data["Password"] = TERMINAL_PASSWORD
    token_str = "".join(str(data[k]) for k in sorted(data.keys()))
    return hashlib.sha256(token_str.encode()).hexdigest()


@sentry_span(op="payment.init")
async def init_payment(
    order_id: str,
    amount: int,
    description: str,
    success_url: str | None = None,
    fail_url: str | None = None,
) -> dict:
    payload = {
        "TerminalKey": TERMINAL_KEY,
        "Amount": amount,
        "OrderId": order_id,
        "Description": description,
    }
    if success_url:
        payload["SuccessURL"] = success_url
    if fail_url:
        payload["FailURL"] = fail_url
    payload["Token"] = _generate_token(payload)

    async with httpx.AsyncClient(timeout=10.0, verify=_SSL_CONTEXT) as client:
        response = await client.post(f"{BASE_URL}/Init", json=payload)
        response.raise_for_status()
        return response.json()


@sentry_span(op="payment.get_state")
async def get_payment_state(payment_id: int) -> dict:
    payload = {
        "TerminalKey": TERMINAL_KEY,
        "PaymentId": payment_id,
    }
    payload["Token"] = _generate_token(payload)

    async with httpx.AsyncClient(timeout=10.0, verify=_SSL_CONTEXT) as client:
        response = await client.post(f"{BASE_URL}/GetState", json=payload)
        response.raise_for_status()
        return response.json()


@sentry_span(op="payment.cancel")
async def cancel_payment(payment_id: int) -> dict:
    payload = {
        "TerminalKey": TERMINAL_KEY,
        "PaymentId": payment_id,
    }
    payload["Token"] = _generate_token(payload)

    async with httpx.AsyncClient(timeout=10.0, verify=_SSL_CONTEXT) as client:
        response = await client.post(f"{BASE_URL}/Cancel", json=payload)
        response.raise_for_status()
        return response.json()
