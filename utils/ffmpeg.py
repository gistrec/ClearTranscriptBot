"""Utility functions for working with ffmpeg."""
import os
import subprocess
from pathlib import Path

import sentry_sdk


def get_media_duration(source: str | Path) -> float:
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
        out = subprocess.check_output(command, text=True).strip()
        return float(out)
    except Exception as e:
        if os.getenv("ENABLE_SENTRY") == "1":
            sentry_sdk.capture_exception(e)
        return 0.0


def convert_to_ogg(source: str | Path, destination: str | Path) -> Path:
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
    Path
        Path to the converted OGG file.
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
    subprocess.run(command, check=True)
    return dst
