"""Convert Replicate WhisperX segments into user-facing timecoded formats."""
import ast
import logging

from typing import Any, Dict, List, Optional


def parse_result_json(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse a ``result_json`` cell (stored as Python ``repr(dict)``)."""
    if not raw:
        return None
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        logging.exception("timecodes: failed to parse result_json")
        return None
    return value if isinstance(value, dict) else None


def extract_segments(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return a list of ``{start, end, text}`` segments from a Replicate payload."""
    output = payload.get("output")
    if isinstance(output, dict):
        raw_segments = output.get("segments") or []
    elif isinstance(output, list):
        raw_segments = output
    else:
        raw_segments = []

    segments: List[Dict[str, Any]] = []
    for seg in raw_segments:
        if not isinstance(seg, dict):
            continue
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = seg.get("start")
        end = seg.get("end")
        if start is None or end is None:
            continue
        segments.append({"start": float(start), "end": float(end), "text": text})
    return segments


def _fmt_hms(seconds: float, ms_sep: str = ",") -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{ms_sep}{ms:03d}"


def _fmt_short(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_txt(segments: List[Dict[str, Any]]) -> str:
    return "\n".join(f"[{_fmt_short(seg['start'])}] {seg['text']}" for seg in segments)


def format_srt(segments: List[Dict[str, Any]]) -> str:
    blocks = []
    for idx, seg in enumerate(segments, start=1):
        blocks.append(
            f"{idx}\n"
            f"{_fmt_hms(seg['start'])} --> {_fmt_hms(seg['end'])}\n"
            f"{seg['text']}\n"
        )
    return "\n".join(blocks)


def format_vtt(segments: List[Dict[str, Any]]) -> str:
    blocks = ["WEBVTT\n"]
    for seg in segments:
        blocks.append(
            f"{_fmt_hms(seg['start'], ms_sep='.')} --> {_fmt_hms(seg['end'], ms_sep='.')}\n"
            f"{seg['text']}\n"
        )
    return "\n".join(blocks)


FORMATTERS = {
    "txt": (format_txt, "txt"),
    "srt": (format_srt, "srt"),
    "vtt": (format_vtt, "vtt"),
}
