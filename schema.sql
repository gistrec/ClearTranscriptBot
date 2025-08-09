-- Schema definition for ClearTranscriptBot

-- Users table holds Telegram users interacting with the bot
CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    telegram_login VARCHAR(32),
    balance DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    registered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- History of transcription requests made by users
CREATE TABLE IF NOT EXISTS transcription_history (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
    status VARCHAR(32) NOT NULL,
    audio_s3_path TEXT NOT NULL,
    duration_seconds INTEGER,
    result_s3_path TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index to speed up lookups by user
CREATE INDEX IF NOT EXISTS idx_transcription_history_telegram_id
    ON transcription_history(telegram_id);
