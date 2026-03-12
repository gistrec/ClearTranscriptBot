"""Unified interface for transcription providers."""

import asyncio
import logging
import os
from typing import Any, Dict, Optional, Tuple

import sentry_sdk

from utils import speechkit

try:
    import replicate
except ImportError:  # pragma: no cover - optional dependency
    replicate = None


DEFAULT_PROVIDER = os.getenv("TRANSCRIPTION_PROVIDER", "speechkit").lower()

REPLICATE_DURATION_SWITCH_SEC = 2 * 60 * 60  # 2 hours
REPLICATE_MODEL_SMALL = os.getenv(
    "REPLICATE_MODEL_SMALL",
    "victor-upmeet/whisperx:84d2ad2d6194fe98a17d2b60bef1c7f910c46b2f6fd38996ca457afd9c8abfcb",
)
REPLICATE_MODEL_LARGE = os.getenv(
    "REPLICATE_MODEL_LARGE", "victor-upmeet/whisperx-a40-large"
)


def _split_operation_id(operation_id: str) -> Tuple[str, str]:
    if ":" not in operation_id:
        return DEFAULT_PROVIDER, operation_id
    provider, op_id = operation_id.split(":", 1)
    return provider, op_id


def _replicate_client() -> Optional["replicate.Client"]:
    token = os.getenv("REPLICATE_API_TOKEN")
    if not token:
        logging.error("REPLICATE_API_TOKEN is not set")
        return None
    if replicate is None:
        logging.error("replicate package is not installed")
        return None
    return replicate.Client(api_token=token)


def _select_replicate_model(duration_seconds: Optional[int]) -> str:
    if duration_seconds and duration_seconds > REPLICATE_DURATION_SWITCH_SEC:
        return REPLICATE_MODEL_LARGE
    return REPLICATE_MODEL_SMALL


async def _start_replicate(audio_url: str, duration_seconds: Optional[int]) -> Optional[str]:
    client = _replicate_client()
    if client is None:
        return None

    model_version = _select_replicate_model(duration_seconds)

    try:
        prediction = await asyncio.to_thread(
            client.predictions.create,
            version=model_version,
            input={"audio_file": audio_url},
        )
        return prediction.id
    except Exception as exc:  # pragma: no cover - network call
        logging.error(f"Failed to start Replicate prediction: {exc}")
        if os.getenv("ENABLE_SENTRY") == "1":
            sentry_sdk.capture_exception(exc)
        return None


async def _check_replicate(operation_id: str) -> Optional[Dict[str, Any]]:
    client = _replicate_client()
    if client is None:
        return None

    try:
        prediction = await asyncio.to_thread(client.predictions.get, operation_id)
    except Exception as exc:  # pragma: no cover - network call
        logging.error(f"Failed to fetch Replicate prediction {operation_id}: {exc}")
        if os.getenv("ENABLE_SENTRY") == "1":
            sentry_sdk.capture_exception(exc)
        return None

    if prediction.status not in {"succeeded", "failed", "canceled"}:
        return None

    return {
        "id": prediction.id,
        "status": prediction.status,
        "output": prediction.output,
        "error": getattr(prediction, "error", None),
    }


async def start_transcription(
    audio_url: str, duration_seconds: Optional[int] = None, language_code: str = "ru-RU"
) -> Optional[str]:
    """Start transcription and return a provider-aware operation id."""

    provider = DEFAULT_PROVIDER
    if provider == "replicate":
        op_id = await _start_replicate(audio_url, duration_seconds)
        return f"replicate:{op_id}" if op_id else None

    op_id = await speechkit.run_transcription(audio_url, language_code)
    return f"speechkit:{op_id}" if op_id else None


async def check_transcription(operation_id: str) -> Optional[Dict[str, Any]]:
    """Return transcription info if finished, otherwise ``None``."""

    provider, op_id = _split_operation_id(operation_id)

    if provider == "replicate":
        payload = await _check_replicate(op_id)
    else:
        payload = await speechkit.fetch_transcription_result(op_id)

    if payload is None:
        return None

    success = False
    if provider == "replicate":
        success = payload.get("status") == "succeeded" and bool(payload.get("output"))
    else:
        success = "response" in payload

    return {
        "provider": provider,
        "payload": payload,
        "success": success,
    }


def _speechkit_text(payload: Dict[str, Any]) -> str:
    return speechkit.parse_text(payload)


def _replicate_text(payload: Dict[str, Any]) -> str:
    output = payload.get("output")
    if isinstance(output, dict):
        segments = output.get("segments") or []
    elif isinstance(output, list) and output and isinstance(output[0], dict):
        segments = output
    else:
        segments = []

    parts = []
    for segment in segments:
        text = (segment.get("text") or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def get_result(check_info: Dict[str, Any]) -> Optional[str]:
    """Extract transcription text from a finished check result."""

    if not check_info.get("success"):
        return None

    provider = check_info.get("provider")
    payload = check_info.get("payload") or {}

    if provider == "replicate":
        return _replicate_text(payload)
    return _speechkit_text(payload)
