"""ElevenLabs Scribe v2 on Replicate: challenger fallback for weak WhisperX results.

Validated on a 25-file prod A/B (July 2026): recovers speech from quiet
recordings the primary model loses, returns honest empty output on silence
(no hallucination loops), and stays coherent from sub-second clips up to
4+ hour files. The challenger runs only on suspicious primary results and
replaces them only when it finds substantially more meaningful text.
"""
import asyncio
import logging
import math
import os
import re

from decimal import Decimal
from typing import Any, Dict, List, Optional

from providers.replicate import USD_TO_RUB, client

from utils.timecodes import extract_segments


MODEL = "elevenlabs/scribe-v2"

# ElevenLabs list price passed through by Replicate: $3.667 per thousand
# billing units, one unit per started minute of input audio.
USD_PER_AUDIO_MINUTE = Decimal("0.003667")

# Recordings quieter than this lose speech to the primary model even with the
# sensitive VAD (A/B: prod 490 chars vs 3535 recovered at -56 dB). Between -40
# and -35 the sensitive VAD mostly copes; below it does not.
QUIET_VOLUME_DB = -40.0

# A primary result whose segments cover less than this share of the audio is
# suspicious (June 2026 gap research: 3.3% of files sit below 0.5). Short
# clips are exempt: a single phrase legitimately covers little of the file.
LOW_COVERAGE = 0.5
LOW_COVERAGE_MIN_DURATION = 60

# The challenger must beat the primary by this margin in meaningful text to
# replace it — protects good results from being swapped for noise (week-1
# conservative value; A/B wins ranged x1.7-x7).
WIN_RATIO = 1.3
MIN_MEANINGFUL_CHARS = 30

# Scribe accepts up to 10 hours; the margin keeps us clear of the hard limit.
MAX_DURATION_SECONDS = 8 * 3600

# Words further apart than this start a new segment; the cap keeps segments
# usable as subtitle blocks.
SEGMENT_GAP_SECONDS = 1.2
SEGMENT_MAX_CHARS = 500

REASON_QUIET = "quiet"
REASON_EMPTY = "empty"
REASON_GARBAGE = "garbage"
REASON_LOW_COVERAGE = "low_coverage"

# Scribe marks non-speech as bracketed audio events («[музыка]», «[смех]»).
# They stay in the delivered text but never count as meaningful speech.
_EVENT_TAG_RE = re.compile(r"\[[^\][\n]{1,40}\]")


def is_enabled() -> bool:
    return os.getenv("SCRIBE_FALLBACK_ENABLED", "1") != "0"


def cost_in_rub(duration_seconds: Optional[int]) -> Decimal:
    """Scribe cost in rubles: one billing unit per started audio minute."""
    minutes = max(1, math.ceil((duration_seconds or 0) / 60))
    return (USD_PER_AUDIO_MINUTE * minutes * USD_TO_RUB).quantize(Decimal("0.01"))


def coverage(payload: Dict[str, Any], duration_seconds: Optional[int]) -> float:
    """Share of the audio covered by recognized segments, capped at 1."""
    if not duration_seconds:
        return 1.0
    covered = sum(seg["end"] - seg["start"] for seg in extract_segments(payload))
    return min(1.0, covered / duration_seconds)


def meaningful_chars(text: Optional[str]) -> int:
    """Length of the speech content: audio-event tags and whitespace excluded."""
    if not text:
        return 0
    return len(re.sub(r"\s", "", _EVENT_TAG_RE.sub("", text)))


def challenger_wins(prod_text: Optional[str], scribe_text: Optional[str]) -> bool:
    scribe_chars = meaningful_chars(scribe_text)
    if scribe_chars < MIN_MEANINGFUL_CHARS:
        return False
    return scribe_chars >= WIN_RATIO * meaningful_chars(prod_text)


def should_try(
    *,
    provider: Optional[str],
    duration_seconds: Optional[int],
    mean_volume_db: Optional[float],
    payload: Dict[str, Any],
    text: Optional[str],
    wrong_language: bool,
    hallucinated: bool,
) -> Optional[str]:
    """Reason to run the challenger on this primary result, or ``None``.

    Wrong-language output is excluded: it already gets the free re-transcribe
    flow, which fixes the language — the challenger cannot.
    """
    if not is_enabled():
        return None
    if provider != "replicate":
        return None
    if wrong_language:
        return None
    if (duration_seconds or 0) > MAX_DURATION_SECONDS:
        return None
    if not text:
        return REASON_EMPTY
    if hallucinated:
        return REASON_GARBAGE
    if mean_volume_db is not None and mean_volume_db < QUIET_VOLUME_DB:
        return REASON_QUIET
    if (
        (duration_seconds or 0) >= LOW_COVERAGE_MIN_DURATION
        and coverage(payload, duration_seconds) < LOW_COVERAGE
    ):
        return REASON_LOW_COVERAGE
    return None


def words_to_segments(output: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Assemble Scribe word stream into WhisperX-style segments.

    A new segment starts on a pause longer than ``SEGMENT_GAP_SECONDS``, on a
    speaker change, or when the current segment outgrows the subtitle-block
    cap. Audio-event tokens flow into the text as-is; spacing tokens only glue
    words together.
    """
    words = output.get("words") or []
    segments: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    current_speaker = None

    for word in words:
        if not isinstance(word, dict):
            continue
        token = word.get("text") or ""
        if word.get("type") == "spacing":
            if current is not None:
                current["text"] += token
            continue
        start = word.get("start")
        end = word.get("end")
        if start is None or end is None:
            continue
        speaker = word.get("speaker_id")
        starts_new = (
            current is None
            or start - current["end"] > SEGMENT_GAP_SECONDS
            or speaker != current_speaker
            or len(current["text"]) >= SEGMENT_MAX_CHARS
        )
        if starts_new:
            if current is not None and current["text"].strip():
                segments.append(current)
            current = {"start": float(start), "end": float(end), "text": token}
            current_speaker = speaker
        else:
            current["text"] += token
            current["end"] = float(end)

    if current is not None and current["text"].strip():
        segments.append(current)

    for segment in segments:
        segment["text"] = segment["text"].strip()
    return segments


def build_payload(prediction_id: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap Scribe output as a WhisperX-compatible ``result_json`` payload.

    Downstream code (timecodes, SRT, refinements, hallucination checks) parses
    ``output.segments``, so the challenger result is stored in the same shape.
    """
    output = info.get("output") or {}
    return {
        "id": prediction_id,
        "status": info.get("status"),
        "output": {
            "detected_language": output.get("language_code") or "ru",
            "segments": words_to_segments(output),
        },
        "error": info.get("error"),
        "predict_time": info.get("predict_time"),
        "fallback_model": MODEL,
    }


async def start_transcription(audio_url: str) -> Optional[str]:
    """Start a Scribe prediction and return its ID, or ``None`` on failure."""
    try:
        prediction = await asyncio.to_thread(
            client.models.predictions.create,
            MODEL,
            input={"audio": audio_url, "language_code": "rus"},
        )
        return prediction.id
    except Exception:
        logging.exception(f"Failed to start Scribe fallback for {audio_url}")
        return None


async def check_transcription(operation_id: str) -> Optional[Dict[str, Any]]:
    """Return prediction info if finished, ``None`` while still running."""
    try:
        prediction = await asyncio.to_thread(client.predictions.get, operation_id)
    except Exception:
        logging.exception(f"Failed to fetch Scribe prediction {operation_id}")
        return None

    if prediction.status not in {"succeeded", "failed", "canceled"}:
        return None

    metrics = getattr(prediction, "metrics", None) or {}
    return {
        "id": prediction.id,
        "status": prediction.status,
        "output": prediction.output,
        "error": getattr(prediction, "error", None),
        "predict_time": metrics.get("predict_time"),
    }
