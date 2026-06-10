import logging

from decimal import Decimal

from telegram import Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM
from database.queries import add_user, get_user, update_transcription

from utils.marketing import track_goal
from utils.sentry import sentry_bind_user, sentry_transaction
from utils.utils import available_time_by_balance
from messengers.telegram import safe_reply_text


def extract_start_payload(text: str) -> str | None:
    if not text or not text.startswith("/start"):
        return None
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else None


@sentry_bind_user
@sentry_transaction(name="message.text", op="telegram.message")
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond to regular text messages."""
    message = update.message
    if message is None:  # edited_message updates have no .message
        return
    user_id = message.from_user.id
    text = message.text or ""

    if not text.startswith("/") and context.user_data:
        feedback_for = context.user_data.pop("awaiting_feedback_for", None)
        if feedback_for is not None:
            update_transcription(feedback_for, rating_comment=text.strip())
            await safe_reply_text(message, "Спасибо! Ваш отзыв поможет нам улучшить качество")
            return

    user = get_user(user_id, PLATFORM_TELEGRAM)
    is_new = user is None

    yclid = None
    if text.startswith("/start"):
        yclid = extract_start_payload(text)
        logging.info("Telegram /start user=%s payload=%r", user_id, yclid)
        if yclid:
            context.application.create_task(track_goal(yclid, "telegram_startbot"))

    if user is None:
        user = add_user(user_id, PLATFORM_TELEGRAM, yclid=yclid)

    balance = Decimal(user.balance or 0)
    duration_str = available_time_by_balance(balance)
    gift = "🎁 Подарили вам <b>почти полтора часа</b> распознавания бесплатно\n\n" if is_new else ""
    await safe_reply_text(
        message,
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
        parse_mode="HTML",
    )


@sentry_bind_user
@sentry_transaction(name="message.unsupported", op="telegram.message")
async def handle_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch-all so photos, stickers etc. get a reply instead of silence."""
    message = update.message
    if message is None:  # edited_message updates have no .message
        return
    await safe_reply_text(
        message,
        "❌ Этот тип сообщения не поддерживается\n"
        "Пожалуйста, отправьте видео или аудио"
    )
