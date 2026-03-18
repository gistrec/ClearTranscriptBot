"""Interact with Yandex Cloud SpeechKit for transcription."""
import os
import httpx
import logging

from decimal import Decimal
from math import ceil
from typing import Dict, Optional


API_URL = "https://transcribe.api.cloud.yandex.net/speech/stt/v2/longRunningRecognize"
OPERATIONS_URL = "https://operation.api.cloud.yandex.net/operations/{id}"

YC_API_KEY = os.environ.get("YC_API_KEY")
YC_FOLDER_ID = os.environ.get("YC_FOLDER_ID")

if not YC_API_KEY or not YC_FOLDER_ID:
    raise RuntimeError("YC_API_KEY and YC_FOLDER_ID must be set")


def _auth_headers() -> Dict[str, str]:
    return {"Authorization": f"Api-Key {YC_API_KEY}"}


def get_model_name(duration_seconds: int) -> str:
    return "Standard"  # В SpeechKit нет разных моделей


def cost_in_rub(duration_s: float, channels: int = 1, deferred: bool = False) -> Decimal:
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
    """
    seconds_rounded = ceil(max(0.0, duration_s))
    ch_even = max(1, channels)
    if ch_even % 2 == 1:
        ch_even += 1
    pairs = ch_even // 2

    seconds_per_pair = max(seconds_rounded, 15)
    total_seconds = seconds_per_pair * pairs
    blocks_15s = (total_seconds + 14) // 15  # ceil(total_seconds / 15)

    rate = Decimal("0.0375") if deferred else Decimal("0.15")
    return (Decimal(blocks_15s) * rate).quantize(Decimal("0.01"))


def get_text(result: dict, separator: str = "\n") -> str:
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


async def check_transcription(operation_id: str) -> Optional[dict]:
    """Check status of *operation_id* and return result if finished."""
    headers = _auth_headers()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            status_response = await client.get(
                OPERATIONS_URL.format(id=operation_id), headers=headers
            )
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
    except Exception:
        logging.exception(f"Failed to fetch transcription result for {operation_id}")
        return None


async def start_transcription(s3_uri: str, duration_seconds: int) -> Optional[str]:
    """Start transcription for *s3_uri* and return operation id or ``None`` on error."""
    headers = _auth_headers()
    payload = {
        "config": {
            "specification": {
                "languageCode": "ru-RU",
                "audioEncoding": "OGG_OPUS",
                "literature_text": True,  # Включает режим нормализации
            },
        },
        "audio": {"uri": s3_uri},
        "folderId": YC_FOLDER_ID,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(API_URL, json=payload, headers=headers)
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
    except Exception:
        logging.exception(f"Failed to start transcription for {s3_uri}")
        return None
