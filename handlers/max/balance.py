"""Handler for /balance command on Max messenger."""
import logging
from decimal import Decimal

import aiomax

from database.models import PLATFORM_MAX
from database.queries import add_user, get_recent_payments, get_user
from payment import PAYMENT_STATUSES
from utils.utils import available_time_by_balance
from utils.sentry import sentry_bind_user_max


@sentry_bind_user_max
async def handle_max_balance(message: aiomax.Message, bot: aiomax.Bot) -> None:
    try:
        user_id = int(message.sender.user_id)
    except (ValueError, TypeError):
        logging.error("Max: cannot parse user_id: %s", message.sender)
        return

    user = get_user(user_id, PLATFORM_MAX)
    if user is None:
        user = add_user(user_id, PLATFORM_MAX, getattr(message.sender, "username", None))

    balance = Decimal(user.balance or 0)
    duration_str = available_time_by_balance(balance)

    topup_lines = []
    for topup in get_recent_payments(user_id, PLATFORM_MAX, limit=5):
        created = topup.created_at.strftime("%d.%m %H:%M") if topup.created_at is not None else "—"
        payment_status = PAYMENT_STATUSES.get(topup.status) or "неизвестно"
        topup_lines.append(f"{created} — {topup.amount} ₽ — {payment_status}")

    topups_text = "\n".join(topup_lines) if topup_lines else "Пополнений пока нет"

    await bot.send_message(
        f"Текущий баланс: {balance} ₽\n"
        f"Хватит на распознавание: {duration_str}\n\n"
        "Последние пополнения:\n"
        f"{topups_text}\n\n"
        "Для пополнения баланса используйте команду /topup",
        chat_id=message.recipient.chat_id,
    )
