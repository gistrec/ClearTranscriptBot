import json

from typing import Optional, Any
from decimal import Decimal
from datetime import datetime

from sqlalchemy import text, update

from database.connection import SessionLocal
from database.models import (
    User, Transcription, Payment, Refinement,
    STATUS_PENDING, STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED,
    STATUS_EXPIRED,
)
from utils.utils import MoscowTimezone


def ping_db() -> None:
    """Verify the database is reachable. Raises if the query fails."""
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))


def add_user(user_id: int, platform: str, yclid: str | None = None) -> User:
    """Create and persist a new user."""
    with SessionLocal() as session:
        user = User(user_id=user_id, user_platform=platform, yclid=yclid)
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


def change_user_balance(user_id: int, platform: str, delta: Decimal) -> User:
    """Add *delta* to user's balance and return updated user."""
    with SessionLocal() as session:
        user = (
            session.query(User)
            .filter(User.user_id == user_id, User.user_platform == platform)
            .with_for_update()
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
    mean_volume_db: float | None = None,
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
            mean_volume_db=mean_volume_db,
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


def has_other_completed_transcription(user_id: int, platform: str, exclude_id: int) -> bool:
    """True if the user has a completed transcription besides *exclude_id*.

    Drives the one-shot ``*_first_transcription`` marketing goal: it must fire
    only when the just-completed task is the user's first successful one.
    """
    with SessionLocal() as session:
        return (
            session.query(Transcription.id)
            .filter(
                Transcription.user_id == user_id,
                Transcription.user_platform == platform,
                Transcription.status == STATUS_COMPLETED,
                Transcription.id != exclude_id,
            )
            .first()
            is not None
        )


def claim_and_charge_transcription(
    transcription_id: int,
    started_at: datetime,
    model: str,
    message_id: str,
    price: Decimal,
) -> str:
    """Atomically transition pending → running and charge the owner's balance.

    Claim and charge happen in one transaction, so a 'running' task always
    means the user has paid, and concurrent clicks can neither start the task
    twice nor drive the balance negative.

    Returns "claimed" if this caller won; "not_pending" if the task already
    left pending (claimed by another click, or cancelled); "insufficient_funds"
    if the balance is below *price* (the task stays pending).
    """
    with SessionLocal() as session:
        task = (
            session.query(Transcription)
            .filter(
                Transcription.id == transcription_id,
                Transcription.status == STATUS_PENDING,
            )
            .with_for_update()
            .one_or_none()
        )
        if task is None:
            return "not_pending"
        user = (
            session.query(User)
            .filter(User.user_id == task.user_id, User.user_platform == task.user_platform)
            .with_for_update()
            .one()
        )
        if (user.balance or Decimal("0")) < price:
            return "insufficient_funds"
        user.balance = user.balance - price
        task.status = STATUS_RUNNING
        task.started_at = started_at
        task.model = model
        task.message_id = message_id
        session.commit()
        return "claimed"


def cancel_transcription_if_pending(transcription_id: int) -> bool:
    """Atomically transition transcription pending → cancelled.

    Returns True if this caller performed the cancellation; False if the
    transcription already left 'pending' (e.g. a concurrent 'Распознать'
    click claimed it for running, so the user has been charged).
    """
    with SessionLocal() as session:
        result = session.execute(
            update(Transcription)
            .where(
                Transcription.id == transcription_id,
                Transcription.status == STATUS_PENDING,
            )
            .values(status=STATUS_CANCELLED)
        )
        session.commit()
        return result.rowcount > 0


def expire_stale_pending_transcriptions(cutoff: datetime) -> int:
    """Mark never-started pending transcriptions created before *cutoff* as expired.

    Only rows still in 'pending' with no started_at are touched, so a concurrent
    'Распознать' click that already claimed a task for running is never affected.
    Returns the number of transcriptions transitioned.
    """
    with SessionLocal() as session:
        result = session.execute(
            update(Transcription)
            .where(
                Transcription.status == STATUS_PENDING,
                Transcription.started_at.is_(None),
                Transcription.created_at < cutoff,
            )
            .values(status=STATUS_EXPIRED)
        )
        session.commit()
        return result.rowcount


def fail_transcription_and_refund(transcription_id: int, *, status: str = STATUS_FAILED, **fields: Any) -> bool:
    """Atomically mark a running transcription failed and refund its price.

    The status transition and the balance refund happen in one transaction
    guarded by the running→terminal claim, so a crash cannot separate them and
    concurrent callers cannot refund twice. *status* is the terminal status to
    set: STATUS_FAILED for genuine errors, STATUS_REJECTED for quality-gate
    refunds (no speech / too noisy). Extra *fields* are applied to the
    transcription row. Returns True if this caller performed the transition.
    """
    with SessionLocal() as session:
        task = (
            session.query(Transcription)
            .filter(
                Transcription.id == transcription_id,
                Transcription.status == STATUS_RUNNING,
            )
            .with_for_update()
            .one_or_none()
        )
        if task is None:
            return False
        task.status = status
        for key, value in fields.items():
            setattr(task, key, value)
        if task.price_for_user:
            user = (
                session.query(User)
                .filter(User.user_id == task.user_id, User.user_platform == task.user_platform)
                .with_for_update()
                .one()
            )
            user.balance = (user.balance or Decimal("0")) + task.price_for_user
        session.commit()
        return True


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


def create_refinement(
    transcription_id: int,
    user_id: int,
    platform: str,
    message_id: str,
    task_type: str = "summarize",
) -> Refinement:
    """Persist a new refinement record in pending state."""
    with SessionLocal() as session:
        record = Refinement(
            transcription_id=transcription_id,
            user_id=user_id,
            user_platform=platform,
            message_id=message_id,
            status=STATUS_PENDING,
            task_type=task_type,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record


def get_refinement(refinement_id: int) -> Optional[Refinement]:
    """Fetch a refinement record by its identifier."""
    with SessionLocal() as session:
        return session.get(Refinement, refinement_id)


def has_refinement(transcription_id: int, task_type: str) -> bool:
    """Return True if a non-failed refinement of the given type exists for the transcription."""
    with SessionLocal() as session:
        return (
            session.query(Refinement)
            .filter(
                Refinement.transcription_id == transcription_id,
                Refinement.task_type == task_type,
                Refinement.status != STATUS_FAILED,
            )
            .first()
        ) is not None


def get_refinements_by_status(status: str) -> list[Refinement]:
    """Return all refinements with the specified *status*."""
    with SessionLocal() as session:
        return (
            session.query(Refinement)
            .filter(Refinement.status == status)
            .all()
        )


def update_refinement(refinement_id: int, **fields: Any) -> Optional[Refinement]:
    """Update fields of an existing refinement record."""
    if not fields:
        return None
    with SessionLocal() as session:
        record = session.get(Refinement, refinement_id)
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
            .with_for_update()
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


def cancel_payment_record(order_id: str) -> bool:
    """Set payment status to CANCELED only if it is still NEW.

    Returns True if this caller performed the transition; False if the payment
    was already handled (e.g. confirmed and credited by the scheduler).
    """
    with SessionLocal() as session:
        result = session.execute(
            update(Payment)
            .where(Payment.order_id == order_id, Payment.status == "NEW")
            .values(status="CANCELED")
        )
        session.commit()
        return result.rowcount > 0


def fail_payment_record(order_id: str, status: str) -> bool:
    """Move a still-NEW payment to a terminal failure *status* reported by Tinkoff.

    Returns True if this caller performed the transition; False if the payment
    was already handled (confirmed, cancelled, or expired) by another path.
    """
    with SessionLocal() as session:
        result = session.execute(
            update(Payment)
            .where(Payment.order_id == order_id, Payment.status == "NEW")
            .values(status=status)
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


def get_landing_stats() -> dict[str, int]:
    """Aggregate counts and total duration for the landing-page stats block."""
    with SessionLocal() as session:
        row = session.execute(
            text(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN status = :completed THEN duration_seconds END), 0) AS sec,
                    SUM(CASE WHEN status = :completed THEN 1 ELSE 0 END) AS completed,
                    SUM(CASE WHEN status = :failed    THEN 1 ELSE 0 END) AS failed
                FROM transcriptions
                """
            ),
            {"completed": STATUS_COMPLETED, "failed": STATUS_FAILED},
        ).one()
        return {
            "duration_seconds": int(row.sec or 0),
            "completed": int(row.completed or 0),
            "failed": int(row.failed or 0),
        }
