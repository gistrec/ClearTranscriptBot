"""Handler for transcription rating callbacks on Max messenger."""
import logging

import aiomax

from database.models import PLATFORM_MAX, is_owner
from database.queries import get_transcription, update_transcription
from messengers.max import make_rating_keyboard, safe_callback_answer, safe_send_message
from utils.sentry import sentry_bind_user_max, sentry_transaction
from utils.utils import RATING_PROMPT, FEEDBACK_PROMPT

_awaiting_feedback: dict[int, int] = {}  # user_id -> transcription_id


@sentry_bind_user_max
@sentry_transaction(name="transcription.rate", op="max.callback")
async def handle_max_rate(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    try:
        _, transcription_id_str, rating_str = callback.payload.split(":")
        transcription_id = int(transcription_id_str)
        rating = int(rating_str)
        user_id = int(callback.user.user_id)
    except (ValueError, AttributeError):
        logging.warning("Max rate: cannot parse callback payload: %s", callback.payload)
        return

    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, user_id, PLATFORM_MAX):
        return

    update_transcription(transcription_id, rating=rating)

    keyboard = make_rating_keyboard(transcription_id, selected=rating)
    await safe_callback_answer(
        callback,
        notification="Спасибо за оценку!",
        text=RATING_PROMPT,
        keyboard=keyboard,
    )

    if rating <= 2:
        _awaiting_feedback[user_id] = transcription_id
        await safe_send_message(bot, FEEDBACK_PROMPT, user_id=user_id)
