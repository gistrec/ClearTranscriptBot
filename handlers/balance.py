from decimal import Decimal

from telegram import Update
from telegram.ext import ContextTypes

from database.queries import add_user, get_user_by_telegram_id

from utils.sentry import sentry_bind_user
from utils.speechkit import available_time_by_balance


@sentry_bind_user
async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    user = get_user_by_telegram_id(telegram_id)
    if user is None:
        user = add_user(telegram_id, update.effective_user.username)
    balance = Decimal(user.balance or 0)
    duration_str = available_time_by_balance(balance)
    await update.message.reply_text(
        f"Текущий баланс: {balance} ₽\n"
        f"Хватит на распознавание: {duration_str}\n\n"
        "Для пополнения баланса напишите @gistrec"
    )
