from decimal import Decimal

from telegram import Update
from telegram.ext import ContextTypes

from database.queries import add_user, get_user_by_telegram_id

from utils.marketing import track_goal
from utils.sentry import sentry_bind_user
from utils.speechkit import available_time_by_balance


def extract_start_payload(text: str) -> str | None:
    if not text or not text.startswith("/start"):
        return None
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else None


@sentry_bind_user
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond to regular text messages."""
    telegram_id = update.message.from_user.id
    user = get_user_by_telegram_id(telegram_id)
    if user is None:
        user = add_user(telegram_id, update.message.from_user.username)

    yclid = extract_start_payload(update.message.text or "")
    if yclid:
        context.application.create_task(track_goal(yclid, "startbot"))

    balance = Decimal(user.balance or 0)
    duration_str = available_time_by_balance(balance)
    await update.message.reply_text(
        "Отправьте видео или аудио — вернём текст.\n"
        "Поддерживаем все популярные форматы:\n"
        "• Видео: mp4, mov, mkv, webm и другие\n"
        "• Аудио: mp3, m4a, wav, ogg/opus, flac и другие\n\n"
        f"Текущий баланс: {balance} ₽\n"
        f"Хватит на распознавание: {duration_str}\n\n"
        "Доступные команды:\n"
        "• /history — история распознаваний\n"
        "• /balance — текущий баланс\n"
        "• /price — стоимость"
    )
