"""Handler for the 'Отменить' callback button on Max messenger."""
import logging

import aiomax

from database.models import PLATFORM_MAX
from database.queries import get_transcription, update_transcription
from utils.utils import format_duration
from utils.sentry import sentry_bind_user_max


@sentry_bind_user_max
async def handle_max_cancel_task(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await callback.answer(notification="")

    try:
        _, id_str = callback.payload.split(":", 1)
        task_id = int(id_str)
    except (ValueError, AttributeError):
        return

    try:
        user_id = int(callback.user.user_id)
    except (ValueError, TypeError, AttributeError):
        logging.error("Max cancel_task: cannot parse user_id from callback")
        return

    message_id = callback.message.body.message_id

    task = get_transcription(task_id)
    if task is None or task.user_id != user_id or task.platform != PLATFORM_MAX:
        await bot.edit_message(message_id, "Задача не найдена", attachments=[])
        return

    if task.status != "pending":
        await bot.edit_message(message_id, "Задача уже обработана", attachments=[])
        return

    update_transcription(task.id, status="cancelled")

    duration_str = format_duration(task.duration_seconds)
    await bot.edit_message(
        message_id,
        f"❌ Задача отменена\n\nДлительность: {duration_str}\nСтоимость: {task.price_for_user} ₽",
        attachments=[],
    )
