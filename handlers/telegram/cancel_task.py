from telegram import Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM
from database.queries import get_transcription, update_transcription

from utils.sentry import sentry_bind_user, sentry_transaction
from utils.utils import format_duration


@sentry_bind_user
@sentry_transaction(name="transcription.cancel", op="telegram.callback")
async def handle_cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    try:
        _, id_str = query.data.split(":", 1)
        task_id = int(id_str)
    except ValueError:
        await query.edit_message_text("Некорректная задача")
        return

    task = get_transcription(task_id)
    user_id = query.from_user.id
    if task is None or task.user_id != user_id or task.user_platform != PLATFORM_TELEGRAM:
        await query.edit_message_text("Задача не найдена")
        return
    if task.status != "pending":
        await query.edit_message_text("Задача уже обработана")
        return

    update_transcription(task.id, status="cancelled")

    duration_str = format_duration(task.duration_seconds)
    await query.edit_message_text(
        f"❌ Задача отменена\n\n"
        f"Длительность: {duration_str}\n"
        f"Стоимость: {task.price_for_user} ₽"
    )
