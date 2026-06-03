"""Interact with Replicate for transcription."""
import os
import asyncio
import logging
import replicate

from decimal import Decimal
from typing import Any, Dict, Optional


MODEL_SMALL = "victor-upmeet/whisperx:655845d6190ef70573c669245f245892cd039df4b880a1e3a65852c09252f5cc"
MODEL_LARGE = "victor-upmeet/whisperx-a40-large:8aad2534a4f2a268a80ab781928cf4bc624b0bbed25afe4d789c70c5781c47b1"

ONE_HOUR = 3600
USD_TO_RUB = Decimal("80")

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

if not REPLICATE_API_TOKEN:
    raise RuntimeError("REPLICATE_API_TOKEN must be set")

client = replicate.Client(api_token=REPLICATE_API_TOKEN)


def get_model(duration_seconds: int) -> str:
    return MODEL_SMALL if duration_seconds < ONE_HOUR else MODEL_LARGE


def get_model_name(duration_seconds: int) -> str:
    return get_model(duration_seconds).split(":")[0]


def cost_in_rub(predict_time_sec: float, model: str = "") -> Decimal:
    """
    Стоимость предсказания Replicate в рублях.

    Тарификация:
    - victor-upmeet/whisperx (A100 80GB): $0.001400/сек
    - victor-upmeet/whisperx-a40-large (L40S): $0.000975/сек
    Конвертация по курсу 80 ₽/$.
    """
    if "whisperx-a40-large" in model:
        rate = Decimal("0.000975")
    else:
        rate = Decimal("0.001400")
    usd = Decimal(str(predict_time_sec)) * rate
    return (usd * USD_TO_RUB).quantize(Decimal("0.01"))


async def start_transcription(audio_url: str, duration_seconds: int) -> Optional[str]:
    """Start a Replicate transcription and return its ID."""
    model = get_model(duration_seconds)
    try:
        transcription = await asyncio.to_thread(
            client.predictions.create,
            version=model,
            input={
                "audio_file": audio_url,
                "language_detection_min_prob": 0.7,
                "language_detection_max_tries": 5,
            },
        )
        return transcription.id
    except Exception:
        logging.exception(f"Failed to start Replicate transcription for {audio_url}")
        return None


async def check_transcription(operation_id: str) -> Optional[Dict[str, Any]]:
    """Return transcription result if finished, otherwise ``None``."""
    try:
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


def _segments(payload: Dict[str, Any]) -> list:
    output = payload.get("output")
    if isinstance(output, dict):
        return output.get("segments") or []
    if isinstance(output, list) and output and isinstance(output[0], dict):
        return output
    return []


def get_text(payload: Dict[str, Any]) -> str:
    """Extract transcription text from a Replicate transcription result."""
    parts = []
    for segment in _segments(payload):
        text = (segment.get("text") or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def looks_like_hallucination(payload: Dict[str, Any]) -> bool:
    """Heuristic flag for likely-garbage WhisperX output.

    Two orthogonal signals observed in real misrecognitions: a low mean
    ``avg_logprob`` (genuine speech stays above -0.17, hallucinations fall
    below -0.38), and a long segment text repeated several times (looping).
    """
    segments = _segments(payload)

    logprobs = [
        s["avg_logprob"]
        for s in segments
        if isinstance(s.get("avg_logprob"), (int, float))
    ]
    if logprobs and sum(logprobs) / len(logprobs) < -0.30:
        return True

    counts: Dict[str, int] = {}
    for segment in segments:
        text = (segment.get("text") or "").strip()
        if len(text) >= 15:
            counts[text] = counts.get(text, 0) + 1
            if counts[text] >= 3:
                return True

    return False
