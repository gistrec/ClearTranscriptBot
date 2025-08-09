"""Main application logic for ClearTranscriptBot."""
from __future__ import annotations

import argparse
from pathlib import Path

from database.queries import add_transcription
from utils.ffmpeg import convert_to_ogg
from utils.s3 import upload_file
from utils.speechkit import run_transcription


def process_file(path: str, bucket: str) -> str:
    """Convert *path* to OGG, upload, transcribe and store result."""
    src = Path(path)
    ogg_path = src.with_suffix(".ogg")
    convert_to_ogg(src, ogg_path)

    s3_uri = upload_file(ogg_path, bucket)
    transcription = run_transcription(s3_uri)
    text = "\n".join([c.get("text", "") for c in transcription.get("chunks", [])])

    add_transcription(
        telegram_id=0,
        status="completed",
        audio_s3_path=str(s3_uri),
        result_s3_path=None,
    )
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe audio using Yandex Cloud")
    parser.add_argument("path", help="Path to input audio/video file")
    parser.add_argument("bucket", help="Destination S3 bucket")
    args = parser.parse_args()

    text = process_file(args.path, args.bucket)
    print(text)


if __name__ == "__main__":
    main()
