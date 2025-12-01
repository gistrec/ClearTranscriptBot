from telegram import Update
from telegram.ext import ContextTypes

from database.queries import get_transcription, update_transcription

from utils.sentry import sentry_bind_user


@sentry_bind_user
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
    telegram_id = query.from_user.id
    if task is None or task.telegram_id != telegram_id:
        await query.edit_message_text("Задача не найдена")
        return
    if task.status != "pending":
        await query.edit_message_text("Задача уже обработана")
        return

    update_transcription(task.id, status="cancelled")

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("Задача отменена")
