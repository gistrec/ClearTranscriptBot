"""Handler for text messages and /start on Max messenger."""
import logging
from decimal import Decimal

import aiomax

from database.models import PLATFORM_MAX
from database.queries import add_user, get_user, update_transcription
from handlers.max.rate_transcription import _awaiting_feedback
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
        logging.warning("Max: cannot parse user_id from sender: %s", message.sender)
        return

    text = message.body.text or ""
    if text and not text.startswith("/"):
        feedback_for = _awaiting_feedback.pop(user_id, None)
        if feedback_for is not None:
            update_transcription(feedback_for, rating_comment=text.strip())
            await safe_send_message(bot, "Спасибо! Ваш отзыв поможет нам улучшить качество",
                chat_id=message.recipient.chat_id)
            return

    user = get_user(user_id, PLATFORM_MAX)
    is_new = user is None
    if is_new:
        user = add_user(user_id, PLATFORM_MAX)

    balance = Decimal(user.balance or 0)
    duration_str = available_time_by_balance(balance)

    gift = "🎁 Подарили вам почти полтора часа распознавания бесплатно\n\n" if is_new else ""
    await safe_send_message(bot,
        f"{gift}Отправьте видео или аудио — вернём текст\n\n"
        "Поддерживаем все популярные форматы:\n"
        "* Видео: mp4, mov, mkv, webm и другие\n"
        "* Аудио: mp3, m4a, wav, ogg/opus, flac и другие\n\n"
        f"Текущий баланс: {balance} ₽\n"
        f"Хватит на распознавание: {duration_str}\n\n"
        "Доступные команды:\n"
        "* /history — история распознаваний\n"
        "* /balance — текущий баланс\n"
        "* /topup — пополнить баланс\n"
        "* /price — стоимость",
        chat_id=message.recipient.chat_id,
    )
