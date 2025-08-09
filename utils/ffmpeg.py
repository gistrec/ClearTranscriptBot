"""Utility functions for working with ffmpeg."""
from __future__ import annotations

import subprocess
from pathlib import Path


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
        str(dst),
    ]
    subprocess.run(command, check=True)
    return dst
