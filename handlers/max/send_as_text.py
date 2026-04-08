"""Handler for the 'Send as text' button on short transcriptions (Max messenger)."""
import logging

import aiomax

from database.queries import get_transcription
from utils.s3 import download_text, object_name_from_url
from utils.sentry import sentry_bind_user_max, sentry_transaction


_MAX_MSG_LEN = 4000


@sentry_bind_user_max
@sentry_transaction(name="send_as_text", op="max.callback")
async def handle_max_send_as_text(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await callback.answer(notification="")

    try:
        _, transcription_id_str = callback.payload.split(":")
        transcription_id = int(transcription_id_str)
        user_id = int(callback.user.user_id)
    except (ValueError, AttributeError):
        logging.error("Max send_as_text: cannot parse callback payload: %s", callback.payload)
        return

    transcription = get_transcription(transcription_id)
    if transcription is None or transcription.user_id != user_id:
        return

    if not transcription.result_s3_path:
        return

    text = await download_text(object_name_from_url(transcription.result_s3_path))
    if not text:
        logging.error("Max send_as_text: failed to download text for transcription %s", transcription_id)
        chat_id = callback.message.recipient.chat_id
        await bot.send_message("Не удалось получить текст", chat_id=chat_id)
        return

    message_id = callback.message.body.message_id
    await bot.edit_message(message_id, callback.message.body.text or "", attachments=[])

    chat_id = callback.message.recipient.chat_id
    for i in range(0, len(text), _MAX_MSG_LEN):
        await bot.send_message(text[i:i + _MAX_MSG_LEN], chat_id=chat_id)
