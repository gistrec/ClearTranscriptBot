import os
import httpx
import hashlib


TERMINAL_KEY = os.environ["TERMINAL_KEY"]
TERMINAL_PASSWORD = os.environ["TERMINAL_PASSWORD"]
ENV = os.getenv("TERMINAL_ENV", "test")

BASE_URL = (
    "https://securepay.tinkoff.ru/v2"
    if ENV == "prod"
    else "https://rest-api-test.tinkoff.ru/v2"
)
# Список тестовых карт Тинькофф:
# https://developer.tbank.ru/eacq/intro/errors/test


PAYMENT_STATUSES = {
    "NEW": "не оплачен",
    "CONFIRMED": "оплачен",
    "AUTHORIZED": "оплачен",
    "CANCELED": "отменён",
}


def _generate_token(params: dict) -> str:
    data = params.copy()
    data["Password"] = TERMINAL_PASSWORD
    token_str = "".join(str(data[k]) for k in sorted(data.keys()))
    return hashlib.sha256(token_str.encode()).hexdigest()


async def init_payment(order_id: str, amount: int, description: str) -> dict:
    payload = {
        "TerminalKey": TERMINAL_KEY,
        "Amount": amount,
        "OrderId": order_id,
        "Description": description,
    }
    payload["Token"] = _generate_token(payload)

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"{BASE_URL}/Init", json=payload)
        response.raise_for_status()
        return response.json()


async def get_payment_state(payment_id: int) -> dict:
    payload = {
        "TerminalKey": TERMINAL_KEY,
        "PaymentId": payment_id,
    }
    payload["Token"] = _generate_token(payload)

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"{BASE_URL}/GetState", json=payload)
        response.raise_for_status()
        return response.json()


async def cancel_payment(payment_id: int) -> dict:
    payload = {
        "TerminalKey": TERMINAL_KEY,
        "PaymentId": payment_id,
    }
    payload["Token"] = _generate_token(payload)

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"{BASE_URL}/Cancel", json=payload)
        response.raise_for_status()
        return response.json()
