"""Utility functions for working with ffmpeg."""
import asyncio
import os
import sentry_sdk

from pathlib import Path


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
        if os.getenv("ENABLE_SENTRY") == "1":
            sentry_sdk.capture_exception(e)
        return 0.0


async def convert_to_ogg(source: str | Path, destination: str | Path) -> Path | None:
    """Convert an audio or video file to OGG using ffmpeg.

    Parameters
    ----------
    source:
        Path to the input file. Any format supported by ffmpeg is accepted.
    destination:
        Path where the resulting OGG file will be stored. The parent directory
        is created automatically.

    Returns
    -------
    Path | None
        Path to the converted OGG file. ``None`` if conversion failed.
    """
    src = Path(source)
    dst = Path(destination)
    dst.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg",
        "-y",  # overwrite output files without asking
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
            return None
        return dst
    except Exception as e:
        if os.getenv("ENABLE_SENTRY") == "1":
            sentry_sdk.capture_exception(e)
        return None
