# ClearTranscriptBot

A simple utility to convert audio/video to OGG, upload it to Yandex Cloud S3 and
obtain a transcript using Yandex Cloud SpeechKit.

## Modules

- `utils/ffmpeg.py` – conversion to OGG using `ffmpeg`.
- `utils/s3.py` – upload helper for Yandex Cloud S3 (S3-compatible).
- `utils/speechkit.py` – request transcription from SpeechKit.
- `database/connection.py` – MySQL connection setup via SQLAlchemy.
- `database/models.py` – SQLAlchemy models for application tables.
- `database/queries.py` – helper functions for common database operations.
- `main.py` – glue code tying everything together.

## Environment variables

### Telegram

- `TELEGRAM_BOT_TOKEN` – token used to authenticate the bot.
- `TELEGRAM_API_ID` – optional, required only when using a local Bot API server.
- `TELEGRAM_API_HASH` – optional, required only when using a local Bot API server.
- `USE_LOCAL_PTB` – set to any value to use a local Bot API server running at
  `http://127.0.0.1:8081`. You need to run the Bot API server locally (see
  below).

### MySQL

- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_DB`

### Yandex Cloud

#### S3

- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`
- `S3_ENDPOINT`
- `S3_BUCKET`

#### SpeechKit

- `YC_API_KEY`
- `YC_FOLDER_ID`

## Local Bot API server

To handle large files you can run a local copy of Telegram's Bot API server.
Example using Docker:

```bash
docker run -d --name tg-bot-api \
  -p 8081:8081 \
  -v /var/lib/telegram-bot-api:/var/lib/telegram-bot-api \
  -e TELEGRAM_API_ID=$TELEGRAM_API_ID \
  -e TELEGRAM_API_HASH=$TELEGRAM_API_HASH \
  -e TELEGRAM_LOCAL=True \
  aiogram/telegram-bot-api:latest \
  --http-ip-address=0.0.0.0 \
  --dir=/var/lib/telegram-bot-api
```

Run this container and set `USE_LOCAL_PTB` so that the bot uses the local
server.

## Database schema

```sql
-- Users table holds Telegram users interacting with the bot
CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    telegram_login VARCHAR(32),
    balance DECIMAL(10,2) NOT NULL DEFAULT 250.00,
    registered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- History of transcription requests made by users
CREATE TABLE IF NOT EXISTS transcription_history (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
    status VARCHAR(32) NOT NULL,
    audio_s3_path TEXT NOT NULL,
    duration_seconds INTEGER,
    price_rub DECIMAL(10,2),
    result_s3_path TEXT,
    result_json TEXT,
    operation_id VARCHAR(128),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index to speed up lookups by user
CREATE INDEX IF NOT EXISTS idx_transcription_history_telegram_id
    ON transcription_history(telegram_id);
```
