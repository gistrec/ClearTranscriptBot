# ClearTranscriptBot

[👉 Try the bot on Telegram][1]

Telegram bot for automatic audio/video transcription:
1. Accepts files from a user
2. Converts them to OGG (via ffmpeg)
3. Uploads to Yandex Cloud S3
4. Requests transcription from Yandex SpeechKit or Replicate WhisperX
5. Sends the transcript back in Telegram

## Features

- 🎙 Supports audio and video files (up to 4 hours)
- 📦 Stores files in Yandex Cloud S3
- 💬 Transcription via Yandex SpeechKit or Replicate WhisperX
- 💰 Balance and billing inside Telegram
- 📜 Full request history
- 🐞 Optional error reporting via Sentry

## Project structure

```
ClearTranscriptBot
├── main.py              # Bot entry point
├── payment.py           # Tinkoff acquiring API wrappers
├── schedulers/          # Periodic task schedulers
│   ├── ffmpeg.py
│   └── transcription.py
├── handlers/            # Telegram update handlers
│   ├── balance.py
│   ├── cancel_task.py
│   ├── create_task.py
│   ├── file.py
│   ├── history.py
│   ├── price.py
│   ├── rate_transcription.py
│   ├── text.py
│   └── topup.py
├── providers/           # Transcription provider implementations
│   ├── replicate.py     # Replicate WhisperX integration
│   └── speechkit.py     # Yandex SpeechKit integration
├── database/            # Data access layer
│   ├── connection.py    # MySQL connection setup via SQLAlchemy
│   ├── models.py        # SQLAlchemy models for application tables
│   └── queries.py       # Helper functions for common database operations
├── utils/               # Helper utilities
│   ├── ffmpeg.py        # Conversion to OGG using ffmpeg
│   ├── marketing.py     # Advertising/tracking: send conversion goals to Yandex Metrica
│   ├── s3.py            # Upload helper for Yandex Cloud S3 (S3-compatible)
│   ├── sentry.py        # Sentry error reporting helpers
│   ├── tokens.py        # LLM token counting helpers
│   ├── transcription.py # Unified entry point routing to provider implementations
│   ├── tg.py            # Telegram-specific helpers
│   └── utils.py         # Shared utility functions
├── docs/                # GitHub Pages legal documents
└── requirements.txt     # Python dependencies list
```

## Environment variables

### Telegram

| Variable             | Description                                                       |
|----------------------|-------------------------------------------------------------------|
| `TELEGRAM_BOT_TOKEN` | Token used to authenticate the bot                                |
| `TELEGRAM_API_ID`    | Optional, required only when using a local Bot API server         |
| `TELEGRAM_API_HASH`  | Optional, required only when using a local Bot API server         |
| `USE_LOCAL_PTB`      | Any value → use a local Bot API server at `http://127.0.0.1:8081` |

### MySQL

| Variable         | Description       |
|------------------|-------------------|
| `MYSQL_USER`     | Database user     |
| `MYSQL_PASSWORD` | Database password |
| `MYSQL_HOST`     | Database host     |
| `MYSQL_PORT`     | Database port     |
| `MYSQL_DB`       | Database name     |

### Yandex Cloud

#### S3

| Variable         | Description       |
|------------------|-------------------|
| `S3_ACCESS_KEY`  | Access key        |
| `S3_SECRET_KEY`  | Secret key        |
| `S3_ENDPOINT`    | S3-compatible URL |
| `S3_BUCKET`      | Bucket name       |


### Transcription providers

| Variable              | Description                |
|-----------------------|----------------------------|
| `YC_API_KEY`          | Yandex SpeechKit API key   |
| `YC_FOLDER_ID`        | Yandex SpeechKit Folder ID |
| `REPLICATE_API_TOKEN` | Replicate API token        |

### Sentry

| Variable        | Description                                                |
|-----------------|------------------------------------------------------------|
| `ENABLE_SENTRY` | Set to `1` to enable Sentry error reporting                |
| `SENTRY_DSN`    | DSN of your Sentry project. Required if `ENABLE_SENTRY=1`  |

### Marketing (Yandex.Metrica)

| Variable       | Description                                                         |
|----------------|---------------------------------------------------------------------|
| `COUNTER_ID`   | Yandex.Metrica counter ID                                           |
| `MEAS_TOKEN`   | Measurement Protocol token (generated in Metrica counter settings)  |
| `BOT_URL`      | Public URL of your bot (e.g. `https://t.me/ClearTranscriptBot`)     |

### Tinkoff acquiring

| Variable            | Description                                  |
|---------------------|----------------------------------------------|
| `TERMINAL_KEY`      | Terminal key from Tinkoff                    |
| `TERMINAL_PASSWORD` | Terminal password from Tinkoff               |
| `TERMINAL_ENV`      | Environment: `test` for sandbox or `prod`    |

## Local Bot API server

To handle large files you can run a local copy of Telegram's Bot API server.
Example using Docker:

```bash
docker run \
    --detach \
    --name tg-bot-api \
    --publish 8081:8081 \
    --volume /var/lib/telegram-bot-api:/var/lib/telegram-bot-api \
    --env TELEGRAM_API_ID=$TELEGRAM_API_ID \
    --env TELEGRAM_API_HASH=$TELEGRAM_API_HASH \
    --env TELEGRAM_LOCAL=True \
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
    telegram_id      BIGINT          PRIMARY KEY,
    telegram_login   VARCHAR(32),
    balance          DECIMAL(10,2)   NOT NULL DEFAULT 150.00,
    default_provider VARCHAR(16)     NOT NULL DEFAULT 'speechkit',
    registered_at    TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- History of transcription requests made by users
CREATE TABLE IF NOT EXISTS transcription_history (
    id                     INTEGER         PRIMARY KEY AUTO_INCREMENT,
    telegram_id            BIGINT          NOT NULL REFERENCES users(telegram_id),
    status                 VARCHAR(32)     NOT NULL,
    audio_s3_path          TEXT            NOT NULL,
    result_json            TEXT,
    llm_tokens_by_encoding JSON,
    duration_seconds       INTEGER,
    price_for_user         DECIMAL(10,2),
    actual_price           DECIMAL(10,2),
    result_s3_path         TEXT,
    provider               VARCHAR(16),
    model                  VARCHAR(64),
    operation_id           VARCHAR(64),
    message_id             INTEGER,
    rating                 INTEGER,
    shadow                 BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at             TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at             TIMESTAMP,
    finished_at            TIMESTAMP
);

-- Index to speed up lookups by user
CREATE INDEX idx_transcription_history_telegram_id
    ON transcription_history(telegram_id);

-- Payments processed via Tinkoff acquiring
CREATE TABLE IF NOT EXISTS payments (
    id               INTEGER         PRIMARY KEY AUTO_INCREMENT,
    telegram_id      BIGINT          NOT NULL REFERENCES users(telegram_id),
    message_id       INTEGER,
    order_id         VARCHAR(64)     NOT NULL UNIQUE,
    payment_id       BIGINT          NOT NULL UNIQUE,
    amount           DECIMAL(10,2)   NOT NULL,
    status           VARCHAR(32)     NOT NULL,
    payment_url      TEXT            NOT NULL,
    description      VARCHAR(255)    NOT NULL,
    tinkoff_response TEXT            NOT NULL,
    created_at       TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_payments_telegram_id
    ON payments(telegram_id);
```

## Installation

Before running, install Python dependencies with:
```bash
pip3 install -r requirements.txt
```

Yandex Cloud MySQL requires SSL. To connect securely, download the CA certificate:
```bash
mkdir -p ~/.mysql && \
wget "https://storage.yandexcloud.net/cloud-certs/CA.pem" \
     --output-document ~/.mysql/root.crt && \
chmod 0600 ~/.mysql/root.crt
```

The certificate will be saved to `~/.mysql/root.crt` and will be used automatically by MySQL clients to establish a secure connection.

## Known issues (mysqlclient)

<details>
<summary>⚠️ pkg-config: command not found</summary>

**On macOS and Linux you may hit an error when installing mysqlclient:**

```bash
Collecting mysqlclient (from -r requirements.txt (line 8))
  Using cached mysqlclient-2.2.7.tar.gz (91 kB)
  Installing build dependencies ... done
  Getting requirements to build wheel ... error
  error: subprocess-exited-with-error

  x Getting requirements to build wheel did not run successfully.
  │ exit code: 1
  ╰─> [35 lines of output]
      /bin/sh: pkg-config: command not found
      *********
      Trying pkg-config --exists mysqlclient
      Command 'pkg-config --exists mysqlclient' returned non-zero exit status 127.
```

In that case install pkg-config: `sudo apt install pkg-config` or `brew install pkg-config`

</details>

<details>
<summary>⚠️ Specify MYSQLCLIENT_CFLAGS and MYSQLCLIENT_LDFLAGS env vars manually</summary>

**On macOS and Linux you may hit an error when installing mysqlclient:**

```bash
Collecting mysqlclient (from -r requirements.txt (line 8))
  Using cached mysqlclient-2.2.7.tar.gz (91 kB)
  Installing build dependencies ... done
  Getting requirements to build wheel ... error
  error: subprocess-exited-with-error

  × Getting requirements to build wheel did not run successfully.
  │ exit code: 1
  ╰─> [29 lines of output]
      Trying pkg-config --exists mysqlclient
      Command 'pkg-config --exists mysqlclient' returned non-zero exit status 1.
      *********
      Exception: Can not find valid pkg-config name.
      Specify MYSQLCLIENT_CFLAGS and MYSQLCLIENT_LDFLAGS env vars manually
      [end of output]
```

In that case install libmysqlclient-dev: `sudo apt install libmysqlclient-dev` or `brew install libmysqlclient-dev`

**libmysqlclient-dev** — is the package that provides the headers and libraries required to build applications that link against MySQL

</details>

## References

- [Yandex Cloud SpeechKit docs][2]
- [Replicate WhisperX examples][3]
- [Telegram Bot API][4]

[1]: https://t.me/ClearTranscriptBot
[2]: https://cloud.yandex.com/docs/speechkit/
[3]: https://replicate.com/victor-upmeet/whisperx-a40-large/examples
[4]: https://core.telegram.org/bots/api
