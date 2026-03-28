"""Handler for transcription rating callbacks on Max messenger."""
import logging

import aiomax

from database.models import PLATFORM_MAX
from database.queries import get_transcription, update_transcription
from handlers.max.common import make_rating_keyboard
from utils.sentry import sentry_bind_user_max


RATING_PROMPT = "Насколько точно распознан текст?"


@sentry_bind_user_max
async def handle_max_rate(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await callback.answer(notification="Спасибо за оценку!")

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

    message_id = callback.message.body.message_id
    keyboard = make_rating_keyboard(transcription_id, selected=rating)
    await bot.edit_message(message_id, RATING_PROMPT, keyboard=keyboard)


@sentry_bind_user_max
async def handle_max_skip_rating(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await callback.answer(notification="")
    message_id = callback.message.body.message_id
    await bot.edit_message(message_id, RATING_PROMPT, attachments=[])
