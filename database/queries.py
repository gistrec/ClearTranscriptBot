"""Helper functions for common database operations."""
from __future__ import annotations

from typing import Optional, Any
from decimal import Decimal

from .connection import SessionLocal
import json

from .models import TopUp, User, TranscriptionHistory


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
    price_rub: Decimal | None = None,
    result_s3_path: str | None = None,
) -> TranscriptionHistory:
    """Persist a new transcription history record."""
    with SessionLocal() as session:
        history = TranscriptionHistory(
            telegram_id=telegram_id,
            status=status,
            audio_s3_path=audio_s3_path,
            duration_seconds=duration_seconds,
            price_rub=price_rub,
            result_s3_path=result_s3_path,
        )
        session.add(history)
        session.commit()
        session.refresh(history)
        return history


def get_transcription(transcription_id: int) -> Optional[TranscriptionHistory]:
    """Fetch a transcription history record by its identifier."""
    with SessionLocal() as session:
        return session.get(TranscriptionHistory, transcription_id)


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


def get_transcriptions_by_status(status: str) -> list[TranscriptionHistory]:
    """Return all transcriptions with the specified *status*."""
    with SessionLocal() as session:
        return (
            session.query(TranscriptionHistory)
            .filter(TranscriptionHistory.status == status)
            .all()
        )


def get_recent_transcriptions(telegram_id: int, limit: int = 10) -> list[TranscriptionHistory]:
    """Return recent transcriptions for *telegram_id* limited by *limit*."""
    with SessionLocal() as session:
        return (
            session.query(TranscriptionHistory)
            .filter(TranscriptionHistory.telegram_id == telegram_id)
            .order_by(TranscriptionHistory.id.desc())
            .limit(limit)
            .all()
        )


def change_user_balance(telegram_id: int, delta: Decimal) -> Optional[User]:
    """Add *delta* to user's balance and return updated user."""
    with SessionLocal() as session:
        user = session.get(User, telegram_id)
        if user is None:
            return None
        user.balance = (user.balance or Decimal("0")) + delta
        session.commit()
        session.refresh(user)
        return user


def create_topup(
    telegram_id: int,
    order_id: str,
    amount: Decimal,
    status: str,
    payment_id: int | None = None,
    payment_url: str | None = None,
    description: str | None = None,
    gateway_response: dict | None = None,
) -> TopUp:
    """Persist a top-up record."""

    with SessionLocal() as session:
        topup = TopUp(
            telegram_id=telegram_id,
            order_id=order_id,
            payment_id=payment_id,
            amount=amount,
            status=status,
            payment_url=payment_url,
            description=description,
            gateway_response=(
                json.dumps(gateway_response, ensure_ascii=False)
                if gateway_response is not None
                else None
            ),
        )
        session.add(topup)
        session.commit()
        session.refresh(topup)
        return topup


def update_topup(order_id: str, **fields: Any) -> Optional[TopUp]:
    """Update fields of an existing top-up."""

    if not fields:
        return None

    with SessionLocal() as session:
        topup = session.query(TopUp).filter(TopUp.order_id == order_id).first()
        if topup is None:
            return None
        for key, value in fields.items():
            setattr(topup, key, value)
        session.commit()
        session.refresh(topup)
        return topup


def get_recent_topups(telegram_id: int, limit: int = 5) -> list[TopUp]:
    """Return recent top-ups for *telegram_id* limited by *limit*."""

    with SessionLocal() as session:
        return (
            session.query(TopUp)
            .filter(TopUp.telegram_id == telegram_id)
            .order_by(TopUp.id.desc())
            .limit(limit)
            .all()
        )
