"""Handler for the 'Create summary' callback on Max messenger."""
import logging

import aiomax

from database.queries import create_refinement, get_transcription, has_refinement
from database.models import PLATFORM_MAX, PROVIDER_REPLICATE, is_owner
from utils.utils import format_duration
from utils.sentry import sentry_bind_user_max, sentry_transaction
from messengers.max import make_summarize_keyboard, safe_callback_answer, safe_send_message, safe_edit_message


@sentry_bind_user_max
@sentry_transaction(name="summarization.create", op="max.callback")
async def handle_max_summarize(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await safe_callback_answer(callback, notification="")

    try:
        _, transcription_id_str = callback.payload.split(":")
        transcription_id = int(transcription_id_str)
        user_id = int(callback.user.user_id)
    except (ValueError, AttributeError):
        logging.warning("Max summarize: cannot parse callback payload: %s", callback.payload)
        return

    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, user_id, PLATFORM_MAX):
        return

    if not transcription.result_json:
        return

    if has_refinement(transcription_id, "summarize"):
        return

    message_id = callback.message.body.message_id
    chat_id = callback.message.recipient.chat_id

    show_improve = not has_refinement(transcription_id, "improve")
    show_timecodes = transcription.provider == PROVIDER_REPLICATE
    remaining_keyboard = make_summarize_keyboard(transcription_id, show_summarize=False, show_improve=show_improve, show_timecodes=show_timecodes)
    await safe_edit_message(bot, message_id, callback.message.body.text or "", keyboard=remaining_keyboard)

    msg = await safe_send_message(bot,
        f"⏳ Создаю конспект...\n\n"
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
    )
