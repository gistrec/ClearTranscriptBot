"""Handler for /topup command and payment callbacks on Max messenger."""
import logging
import time

from decimal import Decimal

import aiomax

from database.models import PLATFORM_MAX
from database.queries import (
    add_user,
    get_user,
    create_payment,
    get_payment_by_order_id,
    update_payment,
    confirm_payment,
)
from payment import init_payment, get_payment_state, cancel_payment
from utils.utils import available_time_by_balance, build_topup_text, build_payment_text
from handlers.max.common import make_topup_amounts_keyboard, make_payment_actions_keyboard
from utils.sentry import sentry_bind_user_max, sentry_transaction
from messengers.max import safe_callback_answer, safe_send_message, safe_edit_message


BOT_URL = "https://max.ru/id420529656333_bot"

TOPUP_AMOUNTS = (50, 100, 250, 500)



@sentry_bind_user_max
@sentry_transaction(name="topup", op="max.command")
async def handle_max_topup(message: aiomax.Message, bot: aiomax.Bot) -> None:
    try:
        user_id = int(message.sender.user_id)
    except (ValueError, TypeError):
        logging.error("Max topup: cannot parse user_id: %s", message.sender)
        return

    user = get_user(user_id, PLATFORM_MAX)
    if user is None:
        add_user(user_id, PLATFORM_MAX)

    await safe_send_message(bot,
        build_topup_text("Выберите сумму пополнения"),
        chat_id=message.recipient.chat_id,
        keyboard=make_topup_amounts_keyboard(),
        format="markdown",
        disable_link_preview=True,
    )


@sentry_bind_user_max
@sentry_transaction(name="topup_callback", op="max.callback")
async def handle_max_topup_callback(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await safe_callback_answer(callback, notification="")

    try:
        user_id = int(callback.user.user_id)
    except (ValueError, TypeError, AttributeError):
        logging.error("Max topup_callback: cannot parse user_id")
        return

    message_id = callback.message.body.message_id
    chat_id = callback.message.recipient.chat_id

    if callback.payload == "topup:cancel":
        await safe_edit_message(bot, message_id, "🚫 Пополнение отменено", attachments=[])
        return

    try:
        _, amount_str = (callback.payload or "").split(":", 1)
        amount = int(amount_str)
    except (ValueError, AttributeError):
        logging.exception("Max topup: invalid callback payload: %s", callback.payload)
        await safe_edit_message(bot, message_id, "Некорректная сумма пополнения", attachments=[])
        return

    if amount not in TOPUP_AMOUNTS:
        logging.error("Max topup: unavailable amount: %s", amount)
        await safe_edit_message(bot, message_id, "Сумма пополнения недоступна", attachments=[])
        return

    await safe_edit_message(bot, message_id, build_topup_text(f"Сумма пополнения: {amount} ₽"), attachments=[], format="markdown")

    order_id = f"max-{user_id}-{int(time.time() * 1000)}"

    if get_payment_by_order_id(order_id) is not None:
        logging.warning("Max topup: duplicate callback for order_id: %s", order_id)
        return

    description = f"Пополнение баланса на {amount} руб"
    amount_kopeks = int(Decimal(amount) * 100)

    try:
        tinkoff_response = await init_payment(
            order_id, amount_kopeks, description,
            success_url=BOT_URL,
            fail_url=BOT_URL,
        )
        payment_status = tinkoff_response.get("Status", None)
        payment_error = tinkoff_response.get("ErrorCode", "0")
        if not payment_status or payment_error != "0":
            raise Exception(f"Payment initialization failed: {tinkoff_response}")
        payment_url = tinkoff_response.get("PaymentURL")
        payment_id = tinkoff_response.get("PaymentId")
        if not payment_url or not payment_id:
            raise Exception(f"Payment response missing PaymentURL or PaymentId: {tinkoff_response}")
    except Exception:
        logging.exception("Max topup: payment init failed for order_id: %s", order_id)
        await safe_send_message(bot,
            "Не удалось создать форму оплаты\n"
            "Попробуйте ещё раз чуть позже",
            chat_id=chat_id,
        )
        return

    create_payment(
        user_id=user_id,
        platform=PLATFORM_MAX,
        order_id=order_id,
        amount=Decimal(amount),
        status=payment_status,
        payment_id=payment_id,
        payment_url=payment_url,
        description=description,
        tinkoff_response=tinkoff_response,
    )

    payment_msg = await safe_send_message(bot,
        build_payment_text(amount, payment_status, payment_url, strikethrough_url=False),
        chat_id=chat_id,
        keyboard=make_payment_actions_keyboard(order_id),
        format="markdown",
        disable_link_preview=True,
    )

    if payment_msg is None:
        return

    update_payment(order_id, message_id=str(payment_msg.body.message_id))


@sentry_bind_user_max
@sentry_transaction(name="payment.check", op="max.callback")
async def handle_max_check_payment(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await safe_callback_answer(callback, notification="")

    try:
        order_id = callback.payload.split(":", 2)[2]
        user_id = int(callback.user.user_id)
    except (IndexError, ValueError, AttributeError):
        logging.exception("Max check_payment: invalid callback data: %s", callback.payload)
        await safe_edit_message(bot, callback.message.body.message_id, "Некорректные данные платежа", attachments=[])
        return

    message_id = callback.message.body.message_id
    chat_id = callback.message.recipient.chat_id

    payment = get_payment_by_order_id(order_id)
    if payment is None or payment.user_id != user_id:
        logging.error("Max check_payment: payment not found for order_id: %s", order_id)
        await safe_edit_message(bot, message_id, "Платёж не найден", attachments=[])
        return

    if payment.status in ("CONFIRMED", "AUTHORIZED"):
        await safe_edit_message(bot, message_id, "Платёж уже завершён ранее", attachments=[])
        return

    try:
        tinkoff_response = await get_payment_state(payment.payment_id)
    except Exception:
        logging.exception("Max check_payment: failed to get state for order: %s", order_id)
        await safe_send_message(bot,
            "Не удалось проверить статус платежа\n"
            "Попробуйте ещё раз",
            chat_id=chat_id,
        )
        return

    payment_status = tinkoff_response.get("Status", None)

    if payment_status in ("CONFIRMED", "AUTHORIZED"):
        won, user = confirm_payment(order_id, payment_status)
        if not won:
            await safe_edit_message(bot, message_id, "Платёж уже завершён ранее", attachments=[])
            return

        balance = Decimal(user.balance or 0)
        duration_str = available_time_by_balance(balance)

        await safe_edit_message(bot, message_id,
            build_payment_text(int(payment.amount), payment_status, payment.payment_url, strikethrough_url=True),
            attachments=[],
            format="markdown",
        )
        await safe_send_message(bot,
            f"✅ Платёж на {int(payment.amount)} ₽ успешно завершён\n\n"
            f"Баланс: {balance} ₽\n"
            f"Хватит на распознавание: {duration_str}",
            chat_id=chat_id,
        )
    else:
        await safe_send_message(bot, "❌ Платёж не завершён", chat_id=chat_id)


@sentry_bind_user_max
@sentry_transaction(name="payment.cancel", op="max.callback")
async def handle_max_cancel_payment(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await safe_callback_answer(callback, notification="")

    try:
        order_id = callback.payload.split(":", 2)[2]
        user_id = int(callback.user.user_id)
    except (IndexError, ValueError, AttributeError):
        logging.exception("Max cancel_payment: invalid callback data: %s", callback.payload)
        await safe_edit_message(bot, callback.message.body.message_id, "Некорректные данные платежа", attachments=[])
        return

    message_id = callback.message.body.message_id

    payment = get_payment_by_order_id(order_id)
    if payment is None or payment.user_id != user_id:
        await safe_edit_message(bot, message_id, "Платёж не найден", attachments=[])
        return

    await safe_edit_message(bot, message_id, "🚫 Пополнение отменено", attachments=[])
    update_payment(order_id, status="CANCELED")

    try:
        tinkoff_response = await cancel_payment(payment.payment_id)
        logging.info("Max cancel_payment: Tinkoff response: %s", tinkoff_response)
    except Exception:
        logging.exception("Max cancel_payment: failed to cancel via Tinkoff: %s", order_id)
