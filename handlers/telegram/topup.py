import logging
import time

from decimal import Decimal

from payment import init_payment, cancel_payment

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM, is_owner
from database.queries import add_user, get_user, \
    create_payment, get_payment_by_order_id, update_payment, \
    cancel_payment_record

from utils.sentry import sentry_bind_user, sentry_transaction
from utils.utils import build_topup_text, build_payment_text
from messengers.telegram import safe_edit_message_text, safe_query_answer, safe_reply_text


BOT_URL = "https://t.me/ClearTranscriptBot"

TOPUP_AMOUNTS = (50, 100, 250, 500)


def _build_topup_amounts_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="50 ₽",  callback_data="topup:50"),
            InlineKeyboardButton(text="100 ₽", callback_data="topup:100"),
        ],
        [
            InlineKeyboardButton(text="250 ₽", callback_data="topup:250"),
            InlineKeyboardButton(text="500 ₽", callback_data="topup:500"),
        ],
        [
            InlineKeyboardButton(text="Отменить", callback_data="topup:cancel")
        ]
    ]

    return InlineKeyboardMarkup(buttons)


def _build_payment_actions_keyboard(order_id: str, payment_url: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("💳 Оплатить", url=payment_url),
        ],
        [
            InlineKeyboardButton("Отменить платёж", callback_data=f"payment:cancel:{order_id}"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)



@sentry_bind_user
@sentry_transaction(name="topup", op="telegram.command")
async def handle_topup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = get_user(user_id, PLATFORM_TELEGRAM)
    if user is None:
        add_user(user_id, PLATFORM_TELEGRAM)

    await safe_reply_text(
        update.message,
        text=build_topup_text("Выберите сумму пополнения"),
        reply_markup=_build_topup_amounts_keyboard(),
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )


@sentry_bind_user
@sentry_transaction(name="topup_callback", op="telegram.callback")
async def handle_topup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_query_answer(query)

    if query.data == "topup:cancel":
        await safe_edit_message_text(query,
            text="🚫 Пополнение отменено",
            reply_markup=None,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )
        return

    try:
        _, amount_str = (query.data or "").split(":", 1)
        amount = int(amount_str)
    except (ValueError, AttributeError):
        logging.warning(f"Invalid topup callback data: {query.data}")
        await safe_edit_message_text(query, "Некорректная сумма пополнения")
        return

    if amount not in TOPUP_AMOUNTS:
        logging.warning(f"Unavailable topup amount selected: {amount}")
        await safe_edit_message_text(query, "Сумма пополнения недоступна")
        return

    # Редактируем сообщение с выбором суммы
    await safe_edit_message_text(query,
        text=build_topup_text(f"Сумма пополнения: {amount} ₽"),
        reply_markup=None,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )

    order_id = f"tg-v2-{query.from_user.id}-{int(time.time() * 1000)}"

    if get_payment_by_order_id(order_id) is not None:
        logging.warning("Duplicate topup callback for order_id: %s", order_id)
        return

    description = f"Пополнение баланса на {amount} руб"
    amount_kopeks = int(Decimal(amount) * 100)

    try:
        tinkoff_response = await init_payment(
            order_id, amount_kopeks, description,
            success_url=BOT_URL,
            fail_url=BOT_URL,
        )
        logging.info(f"Payment initialized: {tinkoff_response}")

        payment_status = tinkoff_response.get("Status", None)
        payment_error = tinkoff_response.get("ErrorCode", "0")
        if not payment_status or payment_error != "0":
            raise Exception(f"Payment initialization failed: {tinkoff_response}")

        payment_url = tinkoff_response.get("PaymentURL")
        payment_id = tinkoff_response.get("PaymentId")
        if not payment_url or not payment_id:
            raise Exception(f"Payment response missing PaymentURL or PaymentId: {tinkoff_response}")

    except Exception:
        logging.exception(f"Payment initialization failed for order_id: {order_id}")
        await safe_reply_text(
            query.message,
            "Не удалось создать форму оплаты\n"
            "Попробуйте ещё раз чуть позже"
        )
        return

    create_payment(
        user_id=query.from_user.id,
        platform=PLATFORM_TELEGRAM,
        order_id=order_id,
        amount=Decimal(amount),
        status=payment_status,
        payment_id=payment_id,
        payment_url=payment_url,
        description=description,
        tinkoff_response=tinkoff_response,
    )

    message = await safe_reply_text(
        query.message,
        text=build_payment_text(amount, payment_status),
        reply_markup=_build_payment_actions_keyboard(order_id, payment_url),
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )

    if message is not None:
        update_payment(order_id, message_id=str(message.message_id))


@sentry_bind_user
@sentry_transaction(name="payment.cancel", op="telegram.callback")
async def handle_cancel_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_query_answer(query)

    try:
        order_id = query.data.split(":", 2)[2]
    except (IndexError, AttributeError):
        logging.warning(f"Invalid payment cancel callback data: {query.data}")
        await safe_edit_message_text(query, "Некорректные данные платежа", reply_markup=None)
        return

    payment = get_payment_by_order_id(order_id)
    if not is_owner(payment, query.from_user.id, PLATFORM_TELEGRAM):
        await safe_edit_message_text(query, "Платёж не найден", reply_markup=None)
        return

    if not cancel_payment_record(order_id):
        await safe_edit_message_text(query, "Платёж уже завершён ранее", reply_markup=None)
        return

    await safe_edit_message_text(query,
        text="🚫 Пополнение отменено",
        reply_markup=None,
    )

    try:
        tinkoff_response = await cancel_payment(payment.payment_id)
        logging.info(f"Tinkoff response: {tinkoff_response}")
    except Exception:
        logging.exception(f"Failed to cancel payment for order_id: {order_id}")

        # No need to notify user about cancellation failure,
        # since we already updated the status in our system and UI
