from decimal import Decimal

from telegram import Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM
from database.queries import add_user, get_recent_payments, get_user

from payment import PAYMENT_STATUSES

from utils.sentry import sentry_bind_user
from utils.utils import available_time_by_balance


@sentry_bind_user
async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = get_user(user_id, PLATFORM_TELEGRAM)
    if user is None:
        user = add_user(user_id, PLATFORM_TELEGRAM, update.effective_user.username)
    balance = Decimal(user.balance or 0)
    duration_str = available_time_by_balance(balance)

    topup_lines = []
    for topup in get_recent_payments(user_id, PLATFORM_TELEGRAM, limit=5):
        created = topup.created_at.strftime("%d.%m %H:%M") if topup.created_at is not None else "—"
        payment_status = PAYMENT_STATUSES.get(topup.status) or "неизвестно"

        topup_lines.append(
            f"{created} — {topup.amount} ₽ — {payment_status}"
        )

    topups_text = "\n".join(topup_lines) if topup_lines else "Пополнений пока нет"

    await update.message.reply_text(
        f"Текущий баланс: {balance} ₽\n"
        f"Хватит на распознавание: {duration_str}\n\n"
        "Последние пополнения:\n"
        f"{topups_text}\n\n"
        "Для пополнения баланса используйте команду /topup"
    )
