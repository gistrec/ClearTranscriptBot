"""Handler for text messages and /start on Max messenger."""
import logging
from decimal import Decimal

import aiomax

from database.models import PLATFORM_MAX
from database.queries import add_user, get_user
from utils.utils import available_time_by_balance
from utils.sentry import sentry_bind_user_max, sentry_transaction
from messengers.max import safe_send_message


@sentry_bind_user_max
@sentry_transaction(name="message.text", op="max.message")
async def handle_max_text(message: aiomax.Message, bot: aiomax.Bot) -> None:
    """Respond to text messages with help text and current balance."""
    try:
        user_id = int(message.sender.user_id)
    except (ValueError, TypeError):
        logging.error("Max: cannot parse user_id from sender: %s", message.sender)
        return

    user = get_user(user_id, PLATFORM_MAX)
    if user is None:
        user = add_user(user_id, PLATFORM_MAX)

    balance = Decimal(user.balance or 0)
    duration_str = available_time_by_balance(balance)

    await safe_send_message(bot,
        "Отправьте видео или аудио — вернём текст\n\n"
        "Поддерживаем все популярные форматы:\n"
        "• Видео: mp4, mov, mkv, webm и другие\n"
        "• Аудио: mp3, m4a, wav, ogg/opus, flac и другие\n\n"
        f"Текущий баланс: {balance} ₽\n"
        f"Хватит на распознавание: {duration_str}\n\n"
        "Доступные команды:\n"
        "• /history — история распознаваний\n"
        "• /balance — текущий баланс\n"
        "• /topup — пополнить баланс\n"
        "• /price — стоимость",
        chat_id=message.recipient.chat_id,
    )
