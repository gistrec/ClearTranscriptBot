"""Utility functions for working with ffmpeg."""
import os
import time
import asyncio
import logging
import sentry_sdk

from typing import Tuple
from pathlib import Path


def get_conversion_progress(
    progress_file: str | Path,
    duration_seconds: float,
    started_at: float
) -> Tuple[int, float, float]:
    """Return conversion progress information.

    Returns (percent, elapsed_wall_seconds, eta_seconds_remaining).
    ETA is computed using processing speed inferred from media_time / wall_time.
    """

    now = time.time()
    elapsed = max(0.0, now - started_at)

    if duration_seconds <= 0:
        return 0, elapsed, 0.0

    path = Path(progress_file)
    if not path.exists():
        return 0, elapsed, duration_seconds

    try:
        content = path.read_text()
    except Exception as e:
        logging.error(f"Failed to read progress file {path}: {e}")
        return 0, elapsed, duration_seconds

    out_time_ms = None
    for line in content.splitlines():
        if line.startswith("out_time_ms="):
            try:
                out_time_ms = int(line.split("=", 1)[1])
            except ValueError:
                logging.debug(f"Unexpected progress line: {line}")

    if out_time_ms is None:
        return 0, elapsed, duration_seconds

    processed_seconds = out_time_ms / 1_000_000
    processed = min(processed_seconds, duration_seconds)

    percent = int((processed / duration_seconds) * 100)
    percent = max(0, min(100, percent))

    speed = processed / elapsed if elapsed > 0 else 0.0
    if speed > 0:
        eta = (duration_seconds - processed) / speed
    else:
        eta = duration_seconds - processed  # fallback when no speed yet

    eta = max(0.0, eta)
    return percent, elapsed, eta


async def get_media_duration(source: str | Path) -> float:
    """Return duration of the media file in seconds.

    The function relies on ``ffprobe`` being available in the system PATH.

    Parameters
    ----------
    source:
        Path to the input audio or video file.

    Returns
    -------
    float
        Duration in seconds. Returns ``0.0`` if the duration could not be
        determined.
    """
    src = Path(source)
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(src),
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            if os.getenv("ENABLE_SENTRY") == "1":
                sentry_sdk.capture_message(
                    f"ffprobe failed: {stderr.decode().strip()}"
                )
            return 0.0
        out = stdout.decode().strip()
        return float(out)
    except Exception as e:
        logging.error(f"Failed to get media duration for {source}: {e}")

        if os.getenv("ENABLE_SENTRY") == "1":
            sentry_sdk.capture_exception(e)

        return 0.0


async def convert_to_ogg(
    source: str | Path,
    destination: str | Path,
    progress_file: str | Path
) -> bool:
    """Convert an audio or video file to OGG using ffmpeg.

    Parameters
    ----------
    source:
        Path to the input file. Any format supported by ffmpeg is accepted.
    destination:
        Path where the resulting OGG file will be stored. The parent directory
        is created automatically.
    progress_file:
        Path to a temporary file where ffmpeg will write ``-progress`` updates.

    Returns
    -------
    bool
        ``True`` if conversion succeeded, ``False`` otherwise.
    """
    src = Path(source)
    dst = Path(destination)
    progress = Path(progress_file)
    dst.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg",
        "-y",  # overwrite output files without asking
        "-nostats",
        "-progress",
        str(progress),
        "-i",
        str(src),
        "-vn",
        "-ac",
        "1",
        "-c:a",
        "libopus",
        "-b:a",
        "64k",
        str(dst),
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            if os.getenv("ENABLE_SENTRY") == "1":
                sentry_sdk.capture_message(
                    f"ffmpeg failed: {stderr.decode().strip()}"
                )
            return False
        return True
    except Exception as e:
        logging.error(f"Failed to convert {source} to OGG: {e}")

        if os.getenv("ENABLE_SENTRY") == "1":
            sentry_sdk.capture_exception(e)

        return False
