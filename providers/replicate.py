"""Interact with Replicate for transcription."""
import asyncio
import logging
import replicate
import os

import sentry_sdk

from typing import Any, Dict, Optional


MODEL = "victor-upmeet/whisperx-a40-large:dbe44b08cd7ac712fc6798784661da2bea1cef41efecd1b98db66e3dbf768918"

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

if not REPLICATE_API_TOKEN:
    raise RuntimeError("REPLICATE_API_TOKEN must be set")


async def start_transcription(audio_url: str) -> Optional[str]:
    """Start a Replicate prediction and return its ID."""
    try:
        client = replicate.Client(api_token=REPLICATE_API_TOKEN)
        prediction = await asyncio.to_thread(
            client.predictions.create,
            version=MODEL,
            input={"audio_file": audio_url},
        )
        return prediction.id
    except Exception as exc:  # pragma: no cover - network call
        logging.error(f"Failed to start Replicate prediction: {exc}")
        if os.getenv("ENABLE_SENTRY") == "1":
            sentry_sdk.capture_exception(exc)
        return None


async def check_transcription(operation_id: str) -> Optional[Dict[str, Any]]:
    """Return prediction result if finished, otherwise ``None``."""
    try:
        client = replicate.Client(api_token=REPLICATE_API_TOKEN)
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


def get_text(payload: Dict[str, Any]) -> str:
    """Extract transcription text from a Replicate prediction result."""
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
