"""Handler for transcription rating callbacks on Max messenger."""
import logging

import aiomax

from database.models import PLATFORM_MAX
from database.queries import get_transcription, update_transcription
from handlers.max.common import make_rating_keyboard
from messengers.max import safe_callback_answer, safe_send_message
from utils.sentry import sentry_bind_user_max, sentry_transaction


RATING_PROMPT = "Оцените качество распознавания"
FEEDBACK_PROMPT = "Расскажите, что пошло не так? Напишите пару слов — это поможет улучшить распознавание."

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
        logging.error("Max rate: cannot parse callback payload: %s", callback.payload)
        return

    transcription = get_transcription(transcription_id)
    if transcription is None or transcription.user_id != user_id or transcription.user_platform != PLATFORM_MAX:
        return

    update_transcription(transcription_id, rating=rating)

    file_attachments = [
        att for att in (callback.message.body.attachments or [])
        if att.type == "file"
    ]
    keyboard = make_rating_keyboard(transcription_id, selected=rating)
    await safe_callback_answer(
        callback,
        notification="Спасибо за оценку!",
        text=RATING_PROMPT,
        keyboard=keyboard,
        attachments=file_attachments if file_attachments else None,
    )

    if rating <= 2:
        _awaiting_feedback[user_id] = transcription_id
        await safe_send_message(bot, FEEDBACK_PROMPT, user_id=user_id)
