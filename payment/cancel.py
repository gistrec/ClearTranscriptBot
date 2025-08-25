import os
import requests
import hashlib
from typing import Optional

TERMINAL_KEY = os.environ["TERMINAL_KEY"]
TERMINAL_PASSWORD = os.environ["TERMINAL_PASSWORD"]
ENV = os.getenv("TERMINAL_ENV", "test")

BASE_URL = (
    "https://securepay.tinkoff.ru/v2"
    if ENV == "prod"
    else "https://rest-api-test.tinkoff.ru/v2"
)


def _generate_token(params: dict) -> str:
    data = params.copy()
    data["Password"] = TERMINAL_PASSWORD
    token_str = "".join(str(data[k]) for k in sorted(data))
    return hashlib.sha256(token_str.encode()).hexdigest()


def cancel_payment(payment_id: int, amount: Optional[int] = None) -> dict:
    payload = {
        "TerminalKey": TERMINAL_KEY,
        "PaymentId": payment_id,
    }
    if amount is not None:
        payload["Amount"] = amount
    payload["Token"] = _generate_token(payload)
    response = requests.post(f"{BASE_URL}/Cancel", json=payload, timeout=30)
    response.raise_for_status()
    return response.json()
