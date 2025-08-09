"""Interact with Yandex Cloud SpeechKit for transcription."""
from __future__ import annotations

import os
from typing import Dict, Any, Optional

import requests

API_URL = "https://transcribe.api.cloud.yandex.net/speech/stt/v2/longRunningRecognize"
OPERATIONS_URL = "https://operation.api.cloud.yandex.net/operations/{id}"


def _auth_headers() -> Dict[str, str]:
    token = os.environ.get("YC_IAM_TOKEN")
    if not token:
        raise RuntimeError("YC_IAM_TOKEN must be set")
    return {"Authorization": f"Bearer {token}"}


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
    folder_id = os.environ.get("YC_FOLDER_ID")
    if not folder_id:
        raise RuntimeError("YC_FOLDER_ID must be set")
    headers = _auth_headers()
    payload = {
        "config": {
            "specification": {
                "languageCode": language_code,
                "audioEncoding": "OGG_OPUS",
            },
        },
        "audio": {"uri": s3_uri},
        "folderId": folder_id,
    }
    response = requests.post(API_URL, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()["id"]
