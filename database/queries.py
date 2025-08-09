"""Helper functions for common database operations."""
from __future__ import annotations

from typing import Optional, Any

from .connection import SessionLocal
from .models import User, TranscriptionHistory


def add_user(telegram_id: int, telegram_login: str | None = None) -> User:
    """Create and persist a new user."""
    with SessionLocal() as session:
        user = User(telegram_id=telegram_id, telegram_login=telegram_login)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def get_user_by_telegram_id(telegram_id: int) -> Optional[User]:
    """Fetch a user by their Telegram identifier."""
    with SessionLocal() as session:
        return session.get(User, telegram_id)


def add_transcription(
    telegram_id: int,
    status: str,
    audio_s3_path: str,
    duration_seconds: int | None = None,
    result_s3_path: str | None = None,
) -> TranscriptionHistory:
    """Persist a new transcription history record."""
    with SessionLocal() as session:
        history = TranscriptionHistory(
            telegram_id=telegram_id,
            status=status,
            audio_s3_path=audio_s3_path,
            duration_seconds=duration_seconds,
            result_s3_path=result_s3_path,
        )
        session.add(history)
        session.commit()
        session.refresh(history)
        return history


def update_transcription(transcription_id: int, **fields: Any) -> Optional[TranscriptionHistory]:
    """Update fields of an existing transcription history record."""
    if not fields:
        return None
    with SessionLocal() as session:
        history = session.get(TranscriptionHistory, transcription_id)
        if history is None:
            return None
        for key, value in fields.items():
            setattr(history, key, value)
        session.commit()
        session.refresh(history)
        return history
