from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from database.queries import add_user, create_topup, get_user_by_telegram_id
from payment.init import init_payment
from utils.sentry import sentry_bind_user

TOPUP_AMOUNTS = (50, 100, 300, 500)


def _build_topup_keyboard() -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []

    for amount in TOPUP_AMOUNTS:
        row.append(
            InlineKeyboardButton(
                text=f"{amount} ₽", callback_data=f"topup:{amount}"
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    return InlineKeyboardMarkup(buttons)


@sentry_bind_user
async def handle_topup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    user = get_user_by_telegram_id(telegram_id)
    if user is None:
        add_user(telegram_id, update.effective_user.username)

    text = (
        "Пополняя баланс вы соглашаетесь с условиями публичной оферты "
        "и политикой обработки персональных данных:\n"
        "• Публичная оферта: https://clear-transcript-bot.gistrec.cloud/user-agreement.html\n"
        "• Политика: https://clear-transcript-bot.gistrec.cloud/privacy-policy.html\n\n"
        "Выберите сумму пополнения:"
    )

    await update.message.reply_text(text, reply_markup=_build_topup_keyboard())


@sentry_bind_user
async def handle_topup_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    try:
        _, amount_str = (query.data or "").split(":", 1)
        amount = int(amount_str)
    except (ValueError, AttributeError):
        await query.edit_message_text("Некорректная сумма пополнения")
        return

    if amount not in TOPUP_AMOUNTS:
        await query.edit_message_text("Сумма пополнения недоступна")
        return

    order_id = f"topup-{query.from_user.id}-{uuid4().hex[:8]}"
    description = f"Пополнение баланса на {amount} ₽"
    amount_kopeks = int(Decimal(amount) * 100)

    try:
        payment_response = init_payment(order_id, amount_kopeks, description)
    except Exception:
        await query.message.reply_text(
            "Не удалось создать оплату. Попробуйте ещё раз чуть позже."
        )
        return

    payment_status = payment_response.get("Status", "unknown")
    payment_url = payment_response.get("PaymentURL")
    payment_id = payment_response.get("PaymentId")

    create_topup(
        telegram_id=query.from_user.id,
        order_id=order_id,
        amount=Decimal(amount),
        status=payment_status,
        payment_id=payment_id,
        payment_url=payment_url,
        description=description,
        gateway_response=payment_response,
    )

    response_lines = [f"Счёт на {amount} ₽ создан."]
    response_lines.append(f"Статус: {payment_status}")
    if payment_url:
        response_lines.append(f"Оплатить: {payment_url}")
    else:
        response_lines.append("Ссылка на оплату недоступна. Попробуйте позже.")

    await query.message.reply_text("\n".join(response_lines))

