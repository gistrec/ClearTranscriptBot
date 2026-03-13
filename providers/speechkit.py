"""Interact with Yandex Cloud SpeechKit for transcription."""
import os
import httpx
import logging
import sentry_sdk

from typing import Dict, Optional


API_URL = "https://transcribe.api.cloud.yandex.net/speech/stt/v2/longRunningRecognize"
OPERATIONS_URL = "https://operation.api.cloud.yandex.net/operations/{id}"

YC_API_KEY = os.environ.get("YC_API_KEY")
YC_FOLDER_ID = os.environ.get("YC_FOLDER_ID")

if not YC_API_KEY or not YC_FOLDER_ID:
    raise RuntimeError("YC_API_KEY and YC_FOLDER_ID must be set")


def _auth_headers() -> Dict[str, str]:
    return {"Authorization": f"Api-Key {YC_API_KEY}"}


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
    except Exception as e:
        logging.exception(f"Failed to fetch transcription result for {operation_id}")

        if os.getenv("ENABLE_SENTRY") == "1":
            sentry_sdk.capture_exception(e)

        return None


async def start_transcription(s3_uri: str, language_code: str = "ru-RU") -> Optional[str]:
    """Start transcription for *s3_uri* and return operation id or ``None`` on error."""
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
    except Exception as e:
        logging.exception(f"Failed to start transcription for {s3_uri}")

        if os.getenv("ENABLE_SENTRY") == "1":
            sentry_sdk.capture_exception(e)

        return None
