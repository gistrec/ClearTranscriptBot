"""Periodic scheduler for checking pending payment statuses."""
import logging

from decimal import Decimal
from datetime import datetime, timedelta

from telegram.ext import ContextTypes

from payment import get_payment_state, cancel_payment
from database.queries import (
    get_payments_due_for_check,
    claim_payment_for_check,
    confirm_payment,
    expire_payment,
    update_payment,
)
from utils.utils import MoscowTimezone, available_time_by_balance
from utils.sentry import sentry_transaction


# Age thresholds (seconds) that determine polling frequency
_PHASE1_END = 15 * 60   # 0–15 min   → every 10 s
_PHASE2_END = 60 * 60   # 15–60 min  → every 30 s
_PHASE3_END = 180 * 60  # 60–180 min → every 60 s; after this → expire

_PHASE1_INTERVAL = 10
_PHASE2_INTERVAL = 30
_PHASE3_INTERVAL = 60


def _check_interval(age_seconds: float) -> int:
    if age_seconds < _PHASE1_END:
        return _PHASE1_INTERVAL
    if age_seconds < _PHASE2_END:
        return _PHASE2_INTERVAL
    return _PHASE3_INTERVAL


@sentry_transaction(name="payment.poll", op="task.check")
async def check_pending_payments(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Poll due payments; credit balance when confirmed, expire after 3 hours."""
    sender = context.bot_data.get("sender")
    now = datetime.now(MoscowTimezone)

    for payment in get_payments_due_for_check():
        created_at = payment.created_at.replace(tzinfo=MoscowTimezone)
        age_seconds = (now - created_at).total_seconds()

        if age_seconds >= _PHASE3_END:
            # Sentinel far in the future prevents other workers from racing on expiry
            if not claim_payment_for_check(payment.order_id, now + timedelta(days=1)):
                continue
            await _expire_payment(sender, payment)
            continue

        interval = _check_interval(age_seconds)
        if not claim_payment_for_check(payment.order_id, now + timedelta(seconds=interval)):
            continue

        try:
            tinkoff_response = await get_payment_state(payment.payment_id)
        except Exception:
            logging.exception("Failed to get payment state for order %s", payment.order_id)
            continue

        payment_status = tinkoff_response.get("Status")
        if payment_status not in ("CONFIRMED", "AUTHORIZED"):
            continue

        await _confirm_payment(sender, payment, payment_status)


async def _confirm_payment(sender, payment, payment_status: str) -> None:
    """Atomically confirm payment and notify user.

    Uses confirm_payment() which holds SELECT FOR UPDATE, so only one caller
    (scheduler or manual button) can credit the balance.
    """
    won, user = confirm_payment(payment.order_id, payment_status)
    if not won:
        return  # another path already handled this payment

    if payment.message_id and sender is not None:
        try:
            await sender.remove_keyboard(payment.user_platform, payment.user_id, payment.message_id)
        except Exception:
            logging.exception("Failed to remove keyboard for payment %s", payment.order_id)

    balance = Decimal(user.balance or 0)
    duration_str = available_time_by_balance(balance)

    if sender is not None:
        try:
            await sender.send_message(
                payment.user_platform,
                payment.user_id,
                text=(
                    f"✅ Платёж на {int(payment.amount)} ₽ успешно завершён\n\n"
                    f"Баланс: {balance} ₽\n"
                    f"Хватит на распознавание: {duration_str}"
                ),
            )
        except Exception:
            logging.exception("Failed to notify user about confirmed payment %s", payment.order_id)


async def _expire_payment(sender, payment) -> None:
    """Check provider one last time before expiring.

    If the check fails (network error), reschedule a retry instead of expiring.
    If the provider reports success, confirm the payment.
    Otherwise mark as EXPIRED and cancel with Tinkoff.
    """
    try:
        tinkoff_response = await get_payment_state(payment.payment_id)
        payment_status = tinkoff_response.get("Status")
    except Exception:
        logging.exception(
            "Final status check failed for payment %s; rescheduling retry", payment.order_id
        )
        update_payment(
            payment.order_id,
            next_check_at=datetime.now(MoscowTimezone) + timedelta(seconds=_PHASE3_INTERVAL),
        )
        return

    if payment_status in ("CONFIRMED", "AUTHORIZED"):
        await _confirm_payment(sender, payment, payment_status)
        return

    if not expire_payment(payment.order_id):
        return  # already cancelled by the user or another process

    if payment.message_id and sender is not None:
        try:
            await sender.edit_message(
                payment.user_platform,
                payment.user_id,
                payment.message_id,
                text="Пополнение отменено автоматически — прошло более 3 часов с момента создания",
                tg_markup=None,
            )
        except Exception:
            logging.exception("Failed to edit expired payment message %s", payment.order_id)

    try:
        await cancel_payment(payment.payment_id)
        logging.info("Auto-expired payment %s (age exceeded 3 hours)", payment.order_id)
    except Exception:
        logging.exception("Failed to cancel payment %s via Tinkoff", payment.order_id)
