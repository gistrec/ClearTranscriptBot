"""Interact with Yandex Cloud SpeechKit for transcription."""
from __future__ import annotations

import os
from typing import Dict, Any, Optional

import requests

API_URL = "https://transcribe.api.cloud.yandex.net/speech/stt/v2/longRunningRecognize"
OPERATIONS_URL = "https://operation.api.cloud.yandex.net/operations/{id}"

YC_IAM_TOKEN = os.environ.get("YC_IAM_TOKEN")
YC_FOLDER_ID = os.environ.get("YC_FOLDER_ID")

if not YC_IAM_TOKEN or not YC_FOLDER_ID:
    raise RuntimeError("YC_IAM_TOKEN and YC_FOLDER_ID must be set")


def _auth_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {YC_IAM_TOKEN}"}


def get_transcription(operation_id: str) -> Optional[Dict[str, Any]]:
    """Check status of *operation_id* and return result if finished."""
    headers = _auth_headers()
    status_resp = requests.get(OPERATIONS_URL.format(id=operation_id), headers=headers, timeout=30)
    status_resp.raise_for_status()
    data = status_resp.json()
    if data.get("done"):
        if "response" in data:
            return data["response"]
        raise RuntimeError(data.get("error", "Unknown error"))
    return None


def run_transcription(s3_uri: str, language_code: str = "ru-RU") -> str:
    """Start transcription for *s3_uri* and return operation id."""
    headers = _auth_headers()
    payload = {
        "config": {
            "specification": {
                "languageCode": language_code,
                "audioEncoding": "OGG_OPUS",
            },
        },
        "audio": {"uri": s3_uri},
        "folderId": YC_FOLDER_ID,
    }
    response = requests.post(API_URL, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()["id"]
