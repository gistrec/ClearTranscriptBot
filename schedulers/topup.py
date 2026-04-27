"""Periodic scheduler for checking pending payment statuses."""
import logging

import messengers.telegram as tg_sender
import messengers.max as max_sender

from decimal import Decimal
from datetime import datetime, timedelta

from telegram.ext import ContextTypes

from payment import get_payment_state, cancel_payment
from database.models import PLATFORM_TELEGRAM
from database.queries import (
    get_payments_due_for_check,
    claim_payment_for_check,
    confirm_payment,
    expire_payment,
    update_payment,
)
from utils.utils import MoscowTimezone, available_time_by_balance
from utils.sentry import sentry_transaction, sentry_drop_transaction


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
    payments = get_payments_due_for_check()
    if not payments:
        sentry_drop_transaction()
        return

    max_bot = context.bot_data.get("max_bot")
    now = datetime.now(MoscowTimezone)

    for payment in payments:
        created_at = payment.created_at.replace(tzinfo=MoscowTimezone)
        age_seconds = (now - created_at).total_seconds()

        if age_seconds >= _PHASE3_END:
            # Sentinel far in the future prevents other workers from racing on expiry
            if not claim_payment_for_check(payment.order_id, now + timedelta(days=1)):
                continue
            await _expire_payment(context, max_bot, payment)
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

        await _confirm_payment(context, max_bot, payment, payment_status)


async def _confirm_payment(context: ContextTypes.DEFAULT_TYPE, max_bot, payment, payment_status: str) -> None:
    """Atomically confirm payment and notify user.

    Uses confirm_payment() which holds SELECT FOR UPDATE, so only one caller
    (scheduler or manual button) can credit the balance.
    """
    won, user = confirm_payment(payment.order_id, payment_status)
    if not won:
        return  # another path already handled this payment

    if payment.message_id:
        if payment.user_platform == PLATFORM_TELEGRAM:
            await tg_sender.safe_remove_keyboard(context.bot, payment.user_id, payment.message_id)
        elif max_bot is not None:
            await max_sender.safe_remove_keyboard(max_bot, payment.message_id)

    balance = Decimal(user.balance or 0)
    duration_str = available_time_by_balance(balance)
    text = (
        f"✅ Платёж на {int(payment.amount)} ₽ успешно завершён\n\n"
        f"Баланс: {balance} ₽\n"
        f"Хватит на распознавание: {duration_str}"
    )
    if payment.user_platform == PLATFORM_TELEGRAM:
        await tg_sender.safe_send_message(context.bot, chat_id=int(payment.user_id), text=text)
    elif max_bot is not None:
        await max_sender.safe_send_message(max_bot, text, user_id=int(payment.user_id))


async def _expire_payment(context: ContextTypes.DEFAULT_TYPE, max_bot, payment) -> None:
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
        await _confirm_payment(context, max_bot, payment, payment_status)
        return

    if not expire_payment(payment.order_id):
        return  # already cancelled by the user or another process

    if payment.message_id:
        expire_text = "Пополнение отменено автоматически — прошло более 3 часов с момента создания"
        if payment.user_platform == PLATFORM_TELEGRAM:
            await tg_sender.safe_edit_message(context.bot, payment.user_id, payment.message_id, expire_text)
        elif max_bot is not None:
            await max_sender.safe_edit_message(max_bot, str(payment.message_id), expire_text, attachments=[])

    try:
        await cancel_payment(payment.payment_id)
        logging.info("Auto-expired payment %s (age exceeded 3 hours)", payment.order_id)
    except Exception:
        logging.exception("Failed to cancel payment %s via Tinkoff", payment.order_id)
