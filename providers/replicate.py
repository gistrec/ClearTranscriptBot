"""Interact with Replicate for transcription."""
import os
import re
import asyncio
import logging
import replicate

from decimal import Decimal
from typing import Any, Dict, Optional

from utils.timecodes import is_phantom_segment


MODEL_SMALL = "victor-upmeet/whisperx:655845d6190ef70573c669245f245892cd039df4b880a1e3a65852c09252f5cc"
MODEL_LARGE = "victor-upmeet/whisperx-a40-large:8aad2534a4f2a268a80ab781928cf4bc624b0bbed25afe4d789c70c5781c47b1"

ONE_HOUR = 3600
USD_TO_RUB = Decimal("80")

# Recordings quieter than this (ffmpeg volumedetect mean_volume) get a more
# sensitive VAD: validated complaint cases sat at -38..-91 dB, the quietest
# good recording at -32.8 dB.
QUIET_MEAN_VOLUME_DB = -35.0

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


async def start_transcription(
    audio_url: str,
    duration_seconds: int,
    mean_volume_db: Optional[float] = None,
    language: Optional[str] = None,
) -> Optional[str]:
    """Start a Replicate transcription and return its ID.

    ``language`` forces WhisperX to a specific language (ISO code) for the
    "re-transcribe in another language" retry; left unset it auto-detects.
    """
    model = get_model(duration_seconds)
    payload = {
        "audio_file": audio_url,
        "language_detection_min_prob": 0.9,
        "language_detection_max_tries": 10,
    }
    if language:
        payload["language"] = language
    if mean_volume_db is not None and mean_volume_db < QUIET_MEAN_VOLUME_DB:
        # Default VAD (0.5/0.363) drops quiet speech entirely (missing intros,
        # multi-minute gaps), while lowering it globally reshuffles output on
        # normal recordings. Quiet records (< -35 dB) get a sensitive VAD;
        # everything else keeps the byte-identical default behaviour.
        payload["vad_onset"] = 0.35
        payload["vad_offset"] = 0.25
    try:
        transcription = await asyncio.to_thread(
            client.predictions.create,
            version=model,
            input=payload,
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


async def cancel(operation_id: str) -> bool:
    """Best-effort cancel of a running Replicate prediction."""
    try:
        await asyncio.to_thread(client.predictions.cancel, operation_id)
        return True
    except Exception:
        logging.exception(f"Failed to cancel Replicate transcription {operation_id}")
        return False


def _segments(payload: Dict[str, Any]) -> list:
    output = payload.get("output")
    if isinstance(output, dict):
        raw = output.get("segments") or []
    elif isinstance(output, list) and output and isinstance(output[0], dict):
        raw = output
    else:
        raw = []
    # Drop subtitle-credit hallucinations here, the single chokepoint feeding
    # both get_text and looks_like_hallucination.
    return [
        s for s in raw
        if isinstance(s, dict) and not is_phantom_segment(s.get("text") or "")
    ]


def get_text(payload: Dict[str, Any]) -> str:
    """Extract transcription text from a Replicate transcription result."""
    parts = []
    for segment in _segments(payload):
        text = (segment.get("text") or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


# detected_language codes that, for our Russian/English audience, are almost
# always a misdetection of Russian speech rather than a genuine foreign upload:
# validated against prod ratings (avg <=2, vs ~5 for real de/fr/ar/tr/it/ja).
WRONG_LANGUAGE_CODES = frozenset({"uk", "nn", "kk", "ko", "zh", "es"})

# Scripts a Russian/English speaker would never expect in their own transcript.
# A WhisperX language misdetection renders the whole output in one of these, so
# a substantial share of such letters means "wrong language".
_FOREIGN_SCRIPT_RE = re.compile(
    "["
    "一-鿿"   # CJK (Chinese, Japanese kanji)
    "぀-ヿ"   # Hiragana + Katakana
    "가-힣"   # Hangul
    "؀-ۿ"   # Arabic
    "֐-׿"   # Hebrew
    "฀-๿"   # Thai
    "ऀ-ॿ"   # Devanagari
    "]"
)


def detected_language(payload: Dict[str, Any]) -> Optional[str]:
    """Language code WhisperX reported for the recording, if any."""
    output = payload.get("output")
    if isinstance(output, dict):
        lang = output.get("detected_language")
        if isinstance(lang, str):
            return lang
    return None


def is_wrong_language(payload: Dict[str, Any]) -> bool:
    """Heuristic flag that WhisperX transcribed in the wrong language.

    Either it reported a language that for our audience is almost always a
    misdetection of Russian, or the text is written in a script no Russian or
    English speaker would expect (Chinese, Arabic, Hangul...). Drives the
    "re-transcribe in another language" prompt.
    """
    if detected_language(payload) in WRONG_LANGUAGE_CODES:
        return True
    text = get_text(payload)
    if not text:
        return False
    foreign = len(_FOREIGN_SCRIPT_RE.findall(text))
    letters = sum(1 for ch in text if ch.isalpha())
    return letters > 0 and foreign / letters > 0.20


# Calibrated on real prod cases: genuine hard audio runs to mean ~-0.41, garbage
# to -0.52 and below. Do not raise toward -0.30 — it refunds good transcripts.
_HALLUCINATION_MEAN_LOGPROB = -0.50
_HALLUCINATION_LOOP_SHARE = 0.5


def looks_like_hallucination(payload: Dict[str, Any]) -> bool:
    """Heuristic flag for likely-garbage WhisperX output.

    Two signals, both scaled so a blemish in otherwise-good speech is not
    refunded: a mean ``avg_logprob`` below ``-0.50`` (pervasively low confidence,
    not just a rough patch), or a long segment text repeated enough to make up at
    least half of all segments (looping that dominates the output).
    """
    segments = _segments(payload)
    if not segments:
        return False

    logprobs = [
        s["avg_logprob"]
        for s in segments
        if isinstance(s.get("avg_logprob"), (int, float))
    ]
    if logprobs and sum(logprobs) / len(logprobs) < _HALLUCINATION_MEAN_LOGPROB:
        return True

    counts: Dict[str, int] = {}
    for segment in segments:
        text = (segment.get("text") or "").strip()
        if len(text) >= 15:
            counts[text] = counts.get(text, 0) + 1
    looped = sum(count for count in counts.values() if count >= 3)
    return bool(looped) and looped / len(segments) >= _HALLUCINATION_LOOP_SHARE
