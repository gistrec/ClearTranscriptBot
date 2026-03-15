"""Interact with Replicate for transcription."""
import os
import asyncio
import logging
import replicate

from typing import Any, Dict, Optional


MODEL_SMALL = "victor-upmeet/whisperx:84d2ad2d6194fe98a17d2b60bef1c7f910c46b2f6fd38996ca457afd9c8abfcb"
MODEL_LARGE = "victor-upmeet/whisperx-a40-large:1395a1d7aa48a01094887250475f384d4bae08fd0616f9c405bb81d4174597ea"

ONE_HOUR = 3600

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

if not REPLICATE_API_TOKEN:
    raise RuntimeError("REPLICATE_API_TOKEN must be set")


def get_model(duration_seconds: int) -> str:
    return MODEL_SMALL if duration_seconds < ONE_HOUR else MODEL_LARGE


def get_model_name(duration_seconds: int) -> str:
    return get_model(duration_seconds).split(":")[0]


async def start_transcription(audio_url: str, duration_seconds: int) -> Optional[str]:
    """Start a Replicate transcription and return its ID."""
    model = get_model(duration_seconds)
    try:
        client = replicate.Client(api_token=REPLICATE_API_TOKEN)
        transcription = await asyncio.to_thread(
            client.predictions.create,
            version=model,
            input={"audio_file": audio_url},
        )
        return transcription.id
    except Exception:
        logging.exception(f"Failed to start Replicate transcription for {audio_url}")
        return None


async def check_transcription(operation_id: str) -> Optional[Dict[str, Any]]:
    """Return transcription result if finished, otherwise ``None``."""
    try:
        client = replicate.Client(api_token=REPLICATE_API_TOKEN)
        transcription = await asyncio.to_thread(client.predictions.get, operation_id)
    except Exception:
        logging.exception(f"Failed to fetch Replicate transcription {operation_id}")
        return None

    if transcription.status not in {"succeeded", "failed", "canceled"}:
        return None

    metrics = getattr(transcription, "metrics", None) or {}

    return {
        "id": transcription.id,
        "status": transcription.status,
        "output": transcription.output,
        "error": getattr(transcription, "error", None),
        "predict_time": metrics.get("predict_time"),
    }


def get_text(payload: Dict[str, Any]) -> str:
    """Extract transcription text from a Replicate transcription result."""
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
