"""Interact with Yandex Cloud SpeechKit for transcription."""
import os
import requests

from typing import Dict, Any, Optional
from typing import Optional
from math import ceil
from decimal import Decimal


API_URL = "https://transcribe.api.cloud.yandex.net/speech/stt/v2/longRunningRecognize"
OPERATIONS_URL = "https://operation.api.cloud.yandex.net/operations/{id}"

YC_API_KEY = os.environ.get("YC_API_KEY")
YC_FOLDER_ID = os.environ.get("YC_FOLDER_ID")

if not YC_API_KEY or not YC_FOLDER_ID:
    raise RuntimeError("YC_API_KEY and YC_FOLDER_ID must be set")


def _auth_headers() -> Dict[str, str]:
    return {"Authorization": f"Api-Key {YC_API_KEY}"}


def parse_text(result: dict, separator: str = "\n") -> str:
    """
    Склеивает тексты из chunks, беря alternatives[0].text
    """
    response = result.get("response") or {}
    chunks = response.get("chunks") or []
    parts = []
    for ch in chunks:
        alts = ch.get("alternatives") or []
        if not alts:
            continue
        t = (alts[0].get("text") or "").strip()
        if t:
            parts.append(t)
    return separator.join(parts)


def fetch_transcription_result(operation_id: str) -> Optional[dict]:
    """Check status of *operation_id* and return result if finished."""
    headers = _auth_headers()
    status_response = requests.get(OPERATIONS_URL.format(id=operation_id), headers=headers, timeout=10)
    status_response.raise_for_status()
    # Пример ответа:
    # {
    #     'done': True,
    #     'response': {
    #         '@type': 'type.googleapis.com/yandex.cloud.ai.stt.v2.LongRunningRecognitionResponse'
    #     },
    #     'id': 'e03sncdp55uvg2tfpso1',
    #     'createdAt': '2025-08-09T20:48:53Z',
    #     'createdBy': 'ajekbvv6h80cp2hle7rf',
    #     'modifiedAt': '2025-08-09T20:48:57Z'
    # }
    data = status_response.json()
    if data.get("done"):
        return data

    return None


def run_transcription(s3_uri: str, language_code: str = "ru-RU") -> str:
    """Start transcription for *s3_uri* and return operation id."""
    headers = _auth_headers()
    payload = {
        "config": {
            "specification": {
                "languageCode": language_code,
                "audioEncoding": "OGG_OPUS",
                "literature_text": True,  # Включает режим нормализации
            },
        },
        "audio": {"uri": s3_uri},
        "folderId": YC_FOLDER_ID,
    }
    response = requests.post(API_URL, json=payload, headers=headers, timeout=10)
    response.raise_for_status()
    # Пример ответа:
    # {
    #     'done': False,
    #     'id': 'e03sncdp55uvg2tfpso1',
    #     'createdAt': '2025-08-09T20:48:53Z',
    #     'createdBy': 'ajekbvv6h80cp2hle7rf',
    #     'modifiedAt': '2025-08-09T20:48:53Z'
    # }
    return response.json()["id"]


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


def format_duration(duration_sec: int) -> str:
    """Format duration in seconds as '{min} мин. {sec} сек.' or '{sec} сек.' if minutes are zero."""
    minutes, seconds = divmod(int(duration_sec), 60)
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
