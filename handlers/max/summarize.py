"""Handler for the 'Create summary' callback on Max messenger."""
import logging

import aiomax

from database.queries import create_summarization, get_transcription
from database.models import PLATFORM_MAX
from utils.utils import format_duration
from utils.sentry import sentry_bind_user_max

SUMMARIZE_THRESHOLD = 300  # seconds


@sentry_bind_user_max
async def handle_max_summarize(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await callback.answer(notification="")

    try:
        _, transcription_id_str = callback.payload.split(":")
        transcription_id = int(transcription_id_str)
        user_id = int(callback.user.user_id)
    except (ValueError, AttributeError):
        logging.error("Max summarize: cannot parse callback payload: %s", callback.payload)
        return

    transcription = get_transcription(transcription_id)
    if transcription is None or transcription.user_id != user_id:
        return

    if not transcription.result_s3_path:
        return

    message_id = callback.message.body.message_id
    chat_id = callback.message.recipient.chat_id

    await bot.edit_message(message_id, callback.message.body.text or "", attachments=[])

    msg = await bot.send_message(
        f"⏳ Создаю конспект...\n\nВремя обработки: {format_duration(0)}",
        chat_id=chat_id,
    )

    create_summarization(
        transcription_id=transcription_id,
        user_id=user_id,
        platform=PLATFORM_MAX,
        message_id=str(msg.body.message_id),
    )
