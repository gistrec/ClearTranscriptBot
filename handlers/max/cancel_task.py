"""Handler for the 'Отменить' callback button on Max messenger."""
import logging

import aiomax

from database.models import PLATFORM_MAX
from database.queries import get_transcription, update_transcription
from utils.utils import format_duration
from utils.sentry import sentry_bind_user_max, sentry_transaction
from messengers.max import safe_callback_answer, safe_edit_message


@sentry_bind_user_max
@sentry_transaction(name="transcription.cancel", op="max.callback")
async def handle_max_cancel_task(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await safe_callback_answer(callback, notification="")

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
    if task is None or task.user_id != user_id or task.user_platform != PLATFORM_MAX:
        await safe_edit_message(bot, message_id, "Задача не найдена", attachments=[])
        return

    if task.status != "pending":
        await safe_edit_message(bot, message_id, "Задача уже обработана", attachments=[])
        return

    update_transcription(task.id, status="cancelled")

    duration_str = format_duration(task.duration_seconds)
    await safe_edit_message(bot,
        message_id,
        f"❌ Задача отменена\n\n"
        f"Длительность: {duration_str}\n"
        f"Стоимость: {task.price_for_user} ₽",
        attachments=[],
    )
