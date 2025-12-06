import json
import secrets

from typing import Optional, Any
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from .connection import SessionLocal, engine
from .models import Base, User, TranscriptionHistory, Payment, VkClick


# Ensure all tables (including newly added ones) are present.
Base.metadata.create_all(bind=engine)


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
        return session.query(User).filter(User.telegram_id == telegram_id).one_or_none()


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


def create_payment(
    telegram_id: int,
    order_id: str,
    amount: Decimal,
    status: str,
    payment_id: int,
    payment_url: str,
    description: str,
    tinkoff_response: dict,
) -> Payment:
    with SessionLocal() as session:
        topup = Payment(
            telegram_id=telegram_id,
            order_id=order_id,
            payment_id=payment_id,
            amount=amount,
            status=status,
            payment_url=payment_url,
            description=description,
            tinkoff_response=json.dumps(tinkoff_response, ensure_ascii=False),
        )
        session.add(topup)
        session.commit()
        session.refresh(topup)
        return topup


def get_recent_payments(telegram_id: int, limit: int = 5) -> list[Payment]:
    with SessionLocal() as session:
        return (
            session.query(Payment)
            .filter(Payment.telegram_id == telegram_id)
            .order_by(Payment.id.desc())
            .limit(limit)
            .all()
        )


def get_payment_by_order_id(order_id: str) -> Optional[Payment]:
    with SessionLocal() as session:
        return session.query(Payment).filter(Payment.order_id == order_id).one_or_none()


def update_payment(order_id: str, **fields: Any) -> Optional[Payment]:
    if not fields:
        return None

    with SessionLocal() as session:
        topup = session.query(Payment).filter(Payment.order_id == order_id).first()
        if topup is None:
            return None
        for key, value in fields.items():
            setattr(topup, key, value)
        session.commit()
        session.refresh(topup)
        return topup


def create_vk_click(rb_clickid: str) -> VkClick:
    """Persist a VK Ads click and return the created object."""

    with SessionLocal() as session:
        for _ in range(5):
            click = VkClick(token=secrets.token_hex(16), rb_clickid=rb_clickid)
            session.add(click)
            try:
                session.commit()
                session.refresh(click)
                return click
            except IntegrityError:
                session.rollback()
        raise RuntimeError("Failed to generate unique token for VK Ads click")


def get_vk_click(token: str) -> Optional[VkClick]:
    """Fetch a VK Ads click entry by its token."""

    with SessionLocal() as session:
        return session.query(VkClick).filter(VkClick.token == token).one_or_none()
