"""Interact with Yandex Cloud SpeechKit for transcription."""
from __future__ import annotations

import os
import time
from typing import Dict, Any

import requests

API_URL = "https://transcribe.api.cloud.yandex.net/speech/stt/v2/longRunningRecognize"
OPERATIONS_URL = "https://operation.api.cloud.yandex.net/operations/{id}"


def run_transcription(s3_uri: str, language_code: str = "ru-RU") -> Dict[str, Any]:
    """Request transcription for *s3_uri* and wait for the result.

    The function uses the IAM token and folder id stored in environment
    variables ``YC_IAM_TOKEN`` and ``YC_FOLDER_ID``.
    """
    token = os.environ.get("YC_IAM_TOKEN")
    folder_id = os.environ.get("YC_FOLDER_ID")
    if not token or not folder_id:
        raise RuntimeError("YC_IAM_TOKEN and YC_FOLDER_ID must be set")

    headers = {"Authorization": f"Bearer {token}"}
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
    operation_id = response.json()["id"]

    # Poll operation status until done
    while True:
        status_resp = requests.get(OPERATIONS_URL.format(id=operation_id), headers=headers, timeout=30)
        status_resp.raise_for_status()
        data = status_resp.json()
        if data.get("done"):
            if "response" in data:
                return data["response"]
            raise RuntimeError(data.get("error", "Unknown error"))
        time.sleep(1)
