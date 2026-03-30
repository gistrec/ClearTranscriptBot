import json

from typing import Optional, Any
from decimal import Decimal
from datetime import datetime

from sqlalchemy import update

from .connection import SessionLocal
from .models import User, Transcription, Payment, Summarization, PLATFORM_TELEGRAM
from utils.utils import MoscowTimezone


def add_user(user_id: int, platform: str) -> User:
    """Create and persist a new user."""
    with SessionLocal() as session:
        user = User(user_id=user_id, user_platform=platform)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def get_user(user_id: int, platform: str) -> Optional[User]:
    """Fetch a user by their platform identifier."""
    with SessionLocal() as session:
        return (
            session.query(User)
            .filter(User.user_id == user_id, User.user_platform == platform)
            .one_or_none()
        )


def get_user_by_telegram_id(telegram_id: int) -> Optional[User]:
    """Compatibility shim — fetch a Telegram user by their identifier."""
    return get_user(telegram_id, PLATFORM_TELEGRAM)


def change_user_balance(user_id: int, platform: str, delta: Decimal) -> User:
    """Add *delta* to user's balance and return updated user."""
    with SessionLocal() as session:
        user = (
            session.query(User)
            .filter(User.user_id == user_id, User.user_platform == platform)
            .one()
        )
        user.balance = (user.balance or Decimal("0")) + delta
        session.commit()
        session.refresh(user)
        return user


def add_transcription(
    user_id: int,
    platform: str,
    status: str,
    audio_s3_path: str,
    provider: str | None = None,
    duration_seconds: int | None = None,
    price_for_user: Decimal | None = None,
    result_s3_path: str | None = None,
) -> Transcription:
    """Persist a new transcription history record."""
    with SessionLocal() as session:
        history = Transcription(
            user_id=user_id,
            user_platform=platform,
            status=status,
            audio_s3_path=audio_s3_path,
            provider=provider,
            duration_seconds=duration_seconds,
            price_for_user=price_for_user,
            result_s3_path=result_s3_path,
        )
        session.add(history)
        session.commit()
        session.refresh(history)
        return history


def get_transcription(transcription_id: int) -> Optional[Transcription]:
    """Fetch a transcription history record by its identifier."""
    with SessionLocal() as session:
        return session.get(Transcription, transcription_id)


def update_transcription(transcription_id: int, **fields: Any) -> Optional[Transcription]:
    """Update fields of an existing transcription history record."""
    if not fields:
        return None
    with SessionLocal() as session:
        history = session.get(Transcription, transcription_id)
        if history is None:
            return None
        for key, value in fields.items():
            setattr(history, key, value)
        session.commit()
        session.refresh(history)
        return history


def get_transcriptions_by_status(status: str) -> list[Transcription]:
    """Return all transcriptions with the specified *status*."""
    with SessionLocal() as session:
        return (
            session.query(Transcription)
            .filter(Transcription.status == status)
            .all()
        )


def get_recent_transcriptions(user_id: int, platform: str, limit: int = 10) -> list[Transcription]:
    """Return recent transcriptions for the given user limited by *limit*."""
    with SessionLocal() as session:
        return (
            session.query(Transcription)
            .filter(Transcription.user_id == user_id, Transcription.user_platform == platform)
            .order_by(Transcription.id.desc())
            .limit(limit)
            .all()
        )


def create_summarization(
    transcription_id: int,
    user_id: int,
    platform: str,
    message_id: str,
) -> Summarization:
    """Persist a new summarization record in pending state."""
    with SessionLocal() as session:
        record = Summarization(
            transcription_id=transcription_id,
            user_id=user_id,
            user_platform=platform,
            message_id=message_id,
            status="pending",
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record


def get_summarization(summarization_id: int) -> Optional[Summarization]:
    """Fetch a summarization record by its identifier."""
    with SessionLocal() as session:
        return session.get(Summarization, summarization_id)


def get_summarizations_by_status(status: str) -> list[Summarization]:
    """Return all summarizations with the specified *status*."""
    with SessionLocal() as session:
        return (
            session.query(Summarization)
            .filter(Summarization.status == status)
            .all()
        )


def update_summarization(summarization_id: int, **fields: Any) -> Optional[Summarization]:
    """Update fields of an existing summarization record."""
    if not fields:
        return None
    with SessionLocal() as session:
        record = session.get(Summarization, summarization_id)
        if record is None:
            return None
        for key, value in fields.items():
            setattr(record, key, value)
        session.commit()
        session.refresh(record)
        return record


def create_payment(
    user_id: int,
    platform: str,
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
            user_id=user_id,
            user_platform=platform,
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


def get_recent_payments(user_id: int, platform: str, limit: int = 5) -> list[Payment]:
    with SessionLocal() as session:
        return (
            session.query(Payment)
            .filter(Payment.user_id == user_id, Payment.user_platform == platform)
            .order_by(Payment.id.desc())
            .limit(limit)
            .all()
        )


def get_payments_by_status(status: str) -> list[Payment]:
    """Return all payments with the specified *status*."""
    with SessionLocal() as session:
        return (
            session.query(Payment)
            .filter(Payment.status == status)
            .all()
        )


def get_payments_due_for_check() -> list[Payment]:
    """Return NEW payments whose next_check_at is past."""
    now = datetime.now(MoscowTimezone)
    with SessionLocal() as session:
        return (
            session.query(Payment)
            .filter(
                Payment.status == "NEW",
                Payment.next_check_at <= now,
            )
            .all()
        )


def claim_payment_for_check(order_id: str, next_check_at: datetime) -> bool:
    """Atomically reserve a payment for checking.

    Sets next_check_at only when the row is still NEW and still due.
    Returns True if this caller won the slot; False if another worker already did.
    """
    now = datetime.now(MoscowTimezone)
    with SessionLocal() as session:
        result = session.execute(
            update(Payment)
            .where(
                Payment.order_id == order_id,
                Payment.status == "NEW",
                Payment.next_check_at <= now,
            )
            .values(next_check_at=next_check_at)
        )
        session.commit()
        return result.rowcount > 0


def confirm_payment(order_id: str, payment_status: str) -> tuple[bool, Optional[User]]:
    """Atomically transition payment NEW→paid and credit user balance in one transaction.

    Uses SELECT FOR UPDATE so only one caller (scheduler or button handler) can win the race.
    Returns (True, updated_user) if this caller performed the transition;
    (False, None) if the payment was already handled by someone else.
    """
    with SessionLocal() as session:
        payment = (
            session.query(Payment)
            .filter(Payment.order_id == order_id, Payment.status == "NEW")
            .with_for_update()
            .one_or_none()
        )
        if payment is None:
            return False, None

        payment.status = payment_status
        user = (
            session.query(User)
            .filter(User.user_id == payment.user_id, User.user_platform == payment.user_platform)
            .one()
        )
        user.balance = (user.balance or Decimal("0")) + payment.amount
        session.commit()
        session.refresh(user)
        return True, user


def expire_payment(order_id: str) -> bool:
    """Set payment status to EXPIRED only if it is still NEW.

    Returns True if the transition happened; False if the payment was already
    handled by another path (e.g. manually cancelled by the user).
    """
    with SessionLocal() as session:
        result = session.execute(
            update(Payment)
            .where(Payment.order_id == order_id, Payment.status == "NEW")
            .values(status="EXPIRED")
        )
        session.commit()
        return result.rowcount > 0


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
