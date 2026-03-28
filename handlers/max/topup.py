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
from payment import init_payment, get_payment_state, cancel_payment, PAYMENT_STATUSES
from utils.utils import available_time_by_balance
from handlers.max.common import make_topup_amounts_keyboard, make_payment_actions_keyboard
from utils.sentry import sentry_bind_user_max


BOT_URL = "https://max.ru/id420529656333_bot"

TOPUP_AMOUNTS = (50, 100, 250, 500)


@sentry_bind_user_max
async def handle_max_topup(message: aiomax.Message, bot: aiomax.Bot) -> None:
    try:
        user_id = int(message.sender.user_id)
    except (ValueError, TypeError):
        logging.error("Max topup: cannot parse user_id: %s", message.sender)
        return

    user = get_user(user_id, PLATFORM_MAX)
    if user is None:
        add_user(user_id, PLATFORM_MAX)

    await bot.send_message(
        "Выберите сумму пополнения:",
        chat_id=message.recipient.chat_id,
        keyboard=make_topup_amounts_keyboard(),
    )


@sentry_bind_user_max
async def handle_max_topup_callback(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await callback.answer(notification="")

    try:
        user_id = int(callback.user.user_id)
    except (ValueError, TypeError, AttributeError):
        logging.error("Max topup_callback: cannot parse user_id")
        return

    message_id = callback.message.body.message_id
    chat_id = callback.message.recipient.chat_id

    if callback.payload == "topup:cancel":
        await bot.edit_message(message_id, "Пополнение отменено", attachments=[])
        return

    try:
        _, amount_str = (callback.payload or "").split(":", 1)
        amount = int(amount_str)
    except (ValueError, AttributeError):
        logging.exception("Max topup: invalid callback payload: %s", callback.payload)
        await bot.edit_message(message_id, "Некорректная сумма пополнения", attachments=[])
        return

    if amount not in TOPUP_AMOUNTS:
        logging.error("Max topup: unavailable amount: %s", amount)
        await bot.edit_message(message_id, "Сумма пополнения недоступна", attachments=[])
        return

    await bot.edit_message(message_id, f"Сумма пополнения: {amount} ₽", attachments=[])

    order_id = f"max-{user_id}-{int(time.time() * 1000)}"

    if get_payment_by_order_id(order_id) is not None:
        logging.warning("Max topup: duplicate callback for order_id: %s", order_id)
        return

    description = f"Пополнение баланса на {amount} ₽"
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
        await bot.send_message(
            "Не удалось создать форму оплаты\nПопробуйте ещё раз чуть позже",
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

    payment_msg = await bot.send_message(
        f"Счёт на {amount} ₽ создан\nСтатус: {PAYMENT_STATUSES.get(payment_status, payment_status)}",
        chat_id=chat_id,
        keyboard=make_payment_actions_keyboard(order_id, payment_url),
    )

    update_payment(order_id, message_id=str(payment_msg.body.message_id))


@sentry_bind_user_max
async def handle_max_check_payment(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await callback.answer(notification="")

    try:
        order_id = callback.payload.split(":", 2)[2]
        user_id = int(callback.user.user_id)
    except (IndexError, ValueError, AttributeError):
        logging.exception("Max check_payment: invalid callback data: %s", callback.payload)
        return

    message_id = callback.message.body.message_id
    chat_id = callback.message.recipient.chat_id

    payment = get_payment_by_order_id(order_id)
    if payment is None or payment.user_id != user_id:
        logging.error("Max check_payment: payment not found for order_id: %s", order_id)
        await bot.edit_message(message_id, "Платёж не найден", attachments=[])
        return

    if payment.status in ("CONFIRMED", "AUTHORIZED"):
        await bot.edit_message(message_id, "Платёж уже завершён ранее", attachments=[])
        return

    try:
        tinkoff_response = await get_payment_state(payment.payment_id)
    except Exception:
        logging.exception("Max check_payment: failed to get state for order: %s", order_id)
        await bot.send_message("Не удалось проверить статус платежа\nПопробуйте ещё раз", chat_id=chat_id)
        return

    payment_status = tinkoff_response.get("Status", None)

    if payment_status in ("CONFIRMED", "AUTHORIZED"):
        won, user = confirm_payment(order_id, payment_status)
        if not won:
            await bot.edit_message(message_id, "Платёж уже завершён ранее", attachments=[])
            return

        balance = Decimal(user.balance or 0)
        duration_str = available_time_by_balance(balance)

        await bot.edit_message(message_id, f"✅ Оплачено {int(payment.amount)} ₽", attachments=[])
        await bot.send_message(
            f"✅ Платёж на {int(payment.amount)} ₽ успешно завершён\n\n"
            f"Баланс: {balance} ₽\n"
            f"Хватит на распознавание: {duration_str}",
            chat_id=chat_id,
        )
    else:
        await bot.send_message("❌ Платёж не завершён", chat_id=chat_id)


@sentry_bind_user_max
async def handle_max_cancel_payment(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await callback.answer(notification="")

    try:
        order_id = callback.payload.split(":", 2)[2]
        user_id = int(callback.user.user_id)
    except (IndexError, ValueError, AttributeError):
        logging.exception("Max cancel_payment: invalid callback data: %s", callback.payload)
        return

    message_id = callback.message.body.message_id

    payment = get_payment_by_order_id(order_id)
    if payment is None or payment.user_id != user_id:
        await bot.edit_message(message_id, "Платёж не найден", attachments=[])
        return

    await bot.edit_message(message_id, "Пополнение отменено", attachments=[])
    update_payment(order_id, status="CANCELED")

    try:
        tinkoff_response = await cancel_payment(payment.payment_id)
        logging.info("Max cancel_payment: Tinkoff response: %s", tinkoff_response)
    except Exception:
        logging.exception("Max cancel_payment: failed to cancel via Tinkoff: %s", order_id)
