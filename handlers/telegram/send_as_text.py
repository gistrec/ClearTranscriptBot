"""Handler for the 'Send as text' button on short transcriptions."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM
from database.queries import get_transcription
from utils.s3 import download_text, object_name_from_url
from utils.sentry import sentry_bind_user, sentry_transaction
from messengers.telegram import safe_reply_text


_TG_MAX_LEN = 4096


@sentry_bind_user
@sentry_transaction(name="send_as_text", op="telegram.callback")
async def handle_send_as_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    _, transcription_id_str = query.data.split(":")
    transcription_id = int(transcription_id_str)

    transcription = get_transcription(transcription_id)
    if transcription is None or transcription.user_id != query.from_user.id or transcription.user_platform != PLATFORM_TELEGRAM:
        return

    if not transcription.result_s3_path:
        return

    text = await download_text(object_name_from_url(transcription.result_s3_path))
    if not text:
        logging.error("send_as_text: failed to download text for transcription %s", transcription_id)
        await safe_reply_text(query.message, "Не удалось получить текст")
        return

    try:
        await query.edit_message_reply_markup(reply_markup=None)
        for i in range(0, len(text), _TG_MAX_LEN):
            await safe_reply_text(query.message, text[i:i + _TG_MAX_LEN])
    except Exception:
        logging.exception("send_as_text: failed to send text for transcription %s", transcription_id)
        await safe_reply_text(query.message, "Не удалось отправить текст")
