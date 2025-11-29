import os
import logging
import sentry_sdk

from decimal import Decimal

from handlers import balance
from payment import init_payment, get_payment_state, cancel_payment, PAYMENT_STATUSES

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.helpers import escape_markdown
from telegram.ext import ContextTypes

from database.queries import add_user, get_user_by_telegram_id, change_user_balance, \
    create_payment, get_payment_by_order_id, update_payment

from utils.sentry import sentry_bind_user
from utils.speechkit import available_time_by_balance


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


def _build_payment_actions_keyboard(order_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("Проверить платёж", callback_data=f"payment:check:{order_id}"),
        ],
        [
            InlineKeyboardButton("Отменить платёж", callback_data=f"payment:cancel:{order_id}"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def _build_topup_text(last_line: str) -> str:
    return (
        "Пополняя баланс, вы соглашаетесь с условиями "
        "[публичной оферты](https://clear-transcript-bot.gistrec.cloud/user-agreement.html) "
        "и [политикой обработки персональных данных](https://clear-transcript-bot.gistrec.cloud/privacy-policy.html)\n\n"

        "Доступные способы оплаты:\n"
        "\\* Банковские карты \\(Visa, MasterCard, Мир\\)\n"
        "\\* Система быстрых платежей \\(СБП\\)\n\n"

        f"{last_line}"
    )


def _build_payment_text(amount: int, status: str, payment_url: str, strikethrough_link: bool) -> str:
    safe_url = escape_markdown(payment_url, version=2)

    if strikethrough_link:
        safe_url = f"~{safe_url}~"  # ← только ссылка

    return (
        f"Счёт на {amount} ₽ создан\n"
        f"Статус: {PAYMENT_STATUSES[status]}\n\n"
        f"Оплатить: {safe_url}"
    )


@sentry_bind_user
async def handle_topup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    user = get_user_by_telegram_id(telegram_id)
    if user is None:
        add_user(telegram_id, update.effective_user.username)

    await update.message.reply_text(
        text=_build_topup_text("Выберите сумму пополнения"),
        reply_markup=_build_topup_amounts_keyboard(),
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )


@sentry_bind_user
async def handle_topup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "topup:cancel":
        await query.message.edit_text(
            text=_build_topup_text("Пополнение отменено"),
            reply_markup=None,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )
        return

    try:
        _, amount_str = (query.data or "").split(":", 1)
        amount = int(amount_str)
    except (ValueError, AttributeError) as e:
        logging.error("Invalid topup callback data: %s", query.data)

        if os.getenv("ENABLE_SENTRY") == "1":
            sentry_sdk.capture_message(f"Invalid topup callback data: {query.data}")

        await query.edit_message_text("Некорректная сумма пополнения")
        return

    if amount not in TOPUP_AMOUNTS:
        logging.error("Unavailable topup amount selected: %d", amount)

        if os.getenv("ENABLE_SENTRY") == "1":
            sentry_sdk.capture_message(f"Unavailable topup amount selected: {amount}")

        await query.edit_message_text("Сумма пополнения недоступна")
        return

    # Редактируем сообщение с выбором суммы
    await query.message.edit_text(
        text=_build_topup_text(f"Сумма пополнения: {amount} ₽"),
        reply_markup=None,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )

    order_id = f"topup-{query.from_user.id}-{query.message.message_id}"
    description = f"Пополнение баланса на {amount} ₽"
    amount_kopeks = int(Decimal(amount) * 100)

    try:
        tinkoff_response = await init_payment(order_id, amount_kopeks, description)
        logging.debug(tinkoff_response)

        if not tinkoff_response.get("Success", False) or tinkoff_response.get("ErrorCode", "0") != "0":
            raise Exception(f"Payment initialization failed: {tinkoff_response}")

    except Exception as e:
        logging.error("Payment initialization failed: %s", e)

        if os.getenv("ENABLE_SENTRY") == "1":
            sentry_sdk.capture_exception(e)

        await query.message.reply_text("Не удалось создать форму оплаты. Попробуйте ещё раз чуть позже.")
        return

    payment_status = tinkoff_response.get("Status", "unknown")
    payment_url = tinkoff_response.get("PaymentURL")
    payment_id = tinkoff_response.get("PaymentId")

    logging.info(f"Payment initialized: {tinkoff_response}")

    create_payment(
        telegram_id=query.from_user.id,
        order_id=order_id,
        amount=Decimal(amount),
        status=payment_status,
        payment_id=payment_id,
        payment_url=payment_url,
        description=description,
        tinkoff_response=tinkoff_response,
    )

    message = await query.message.reply_text(
        text=_build_payment_text(amount, payment_status, payment_url, strikethrough_link=False),
        reply_markup=_build_payment_actions_keyboard(order_id),
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )

    update_payment(order_id, message_id=message.message_id)


@sentry_bind_user
async def handle_check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    order_id = query.data.split(":", 2)[2]
    payment = get_payment_by_order_id(order_id)
    if payment is None or payment.telegram_id != query.from_user.id:
        logging.error(f"Payment not found for order_id: {order_id}")
        await query.message.edit_text("Платёж не найден", reply_markup=None)
        return

    if payment.status in ("CONFIRMED", "AUTHORIZED"):
        logging.info(f"Payment already completed for order_id: {order_id}")

        # Удаляем у сообщения кнопки для проверки платежа и отмены
        await query.edit_message_reply_markup(reply_markup=None)

        await query.message.edit_text(
            "Платёж уже завершён ранее",
            reply_markup=None
        )
        return

    tinkoff_response = await get_payment_state(payment.payment_id)
    logging.info(f"Tinkoff response: {tinkoff_response}")

    payment_status = tinkoff_response.get("Status", "unknown")

    if payment_status == "CONFIRMED" or payment_status == "AUTHORIZED":
        user = change_user_balance(payment.telegram_id, payment.amount)
        update_payment(order_id, status=payment_status)

        balance = Decimal(user.balance or 0)
        duration_str = available_time_by_balance(balance)

        # Изменяем сообщение со ссылкой для оплаты
        await query.message.edit_text(
            text=_build_payment_text(
                int(payment.amount),
                payment_status,
                payment.payment_url,
                strikethrough_link=True
            ),
            reply_markup=None,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )

        await query.message.reply_text(
            f"✅ Платёж на {int(payment.amount)} ₽ успешно завершён\n\n"
            f"Баланс: {balance} ₽\n"
            f"Хватит на распознавание: {duration_str}",
        )
        return
    else:
        await query.message.reply_text(f"❌ Платёж не завершён")


@sentry_bind_user
async def handle_cancel_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    order_id = query.data.split(":", 2)[2]
    payment = get_payment_by_order_id(order_id)
    if payment is None or payment.telegram_id != query.from_user.id:
        await query.message.edit_text("Платёж не найден", reply_markup=None)
        return

    await query.message.edit_text(
        text="Пополнение отменено",
        reply_markup=None,
    )

    tinkoff_response = await cancel_payment(payment.payment_id)
    logging.info(f"Tinkoff response: {tinkoff_response}")

    update_payment(order_id, status="CANCELED")
