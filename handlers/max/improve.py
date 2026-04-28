"""Handler for the 'Улучшить текст' callback on Max messenger."""
import logging

import aiomax

from database.queries import create_refinement, get_transcription, has_refinement
from database.models import PLATFORM_MAX
from utils.utils import format_duration, SUMMARIZE_THRESHOLD
from utils.sentry import sentry_bind_user_max, sentry_transaction
from messengers.max import make_summarize_keyboard, make_send_as_text_keyboard, safe_callback_answer, safe_send_message, safe_edit_message


@sentry_bind_user_max
@sentry_transaction(name="improvement.create", op="max.callback")
async def handle_max_improve(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await safe_callback_answer(callback, notification="")

    try:
        _, transcription_id_str = callback.payload.split(":")
        transcription_id = int(transcription_id_str)
        user_id = int(callback.user.user_id)
    except (ValueError, AttributeError):
        logging.error("Max improve: cannot parse callback payload: %s", callback.payload)
        return

    transcription = get_transcription(transcription_id)
    if transcription is None or transcription.user_id != user_id:
        return

    if not transcription.result_s3_path:
        return

    message_id = callback.message.body.message_id
    chat_id = callback.message.recipient.chat_id

    show_summarize = not has_refinement(transcription_id, "summarize")
    duration = transcription.duration_seconds or 0
    if duration > SUMMARIZE_THRESHOLD:
        remaining_keyboard = make_summarize_keyboard(transcription_id, show_summarize=show_summarize, show_improve=False)
    else:
        remaining_keyboard = make_send_as_text_keyboard(transcription_id, show_improve=False)
    await safe_edit_message(bot, message_id, callback.message.body.text or "", keyboard=remaining_keyboard)

    msg = await safe_send_message(bot,
        f"⏳ Улучшаю текст...\n\n"
        f"Время обработки: {format_duration(0)}",
        chat_id=chat_id,
    )
    if msg is None:
        return

    create_refinement(
        transcription_id=transcription_id,
        user_id=user_id,
        platform=PLATFORM_MAX,
        message_id=str(msg.body.message_id),
        task_type="improve",
    )
