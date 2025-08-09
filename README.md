# ClearTranscriptBot

A simple utility to convert audio/video to OGG, upload it to Yandex Cloud S3 and
obtain a transcript using Yandex Cloud SpeechKit.

## Modules

- `utils/ffmpeg.py` – conversion to OGG using `ffmpeg`.
- `utils/s3.py` – upload helper for Yandex Cloud S3 (S3-compatible).
- `utils/speechkit.py` – request transcription from SpeechKit.
- `db.py` – MySQL connection helper.
- `main.py` – glue code tying everything together.

Environment variables are used for credentials.
