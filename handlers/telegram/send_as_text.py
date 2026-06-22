"""Handler for the 'Send as text' button on short transcriptions."""
import asyncio
import logging

from telegram import Update
from telegram.error import RetryAfter
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM, PROVIDER_REPLICATE, is_owner
from database.queries import get_transcription, has_refinement
from utils.transcription import get_result_text
from utils.sentry import sentry_bind_user, sentry_transaction
from messengers.telegram import safe_query_answer, safe_reply_text, safe_edit_message_reply_markup, make_send_as_text_keyboard


_TG_MAX_LEN = 4096
_RETRY_ATTEMPTS = 3


async def _reply_chunk(message, chunk: str):
    """Send one chunk, waiting out flood control instead of dropping the chunk.

    safe_reply_text swallows RetryAfter, which used to leave holes in the
    middle of long transcripts. Returns the sent message or None on failure.
    """
    for _ in range(_RETRY_ATTEMPTS):
        try:
            return await message.reply_text(chunk)
        except RetryAfter as exc:
            logging.warning("send_as_text: flood control, sleeping %ss", exc.retry_after)
            await asyncio.sleep(exc.retry_after + 1)
        except Exception:
            logging.exception("send_as_text: chunk send failed")
            return None
    logging.warning("send_as_text: giving up after repeated flood control")
    return None


@sentry_bind_user
@sentry_transaction(name="send_as_text", op="telegram.callback")
async def handle_send_as_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_query_answer(query)

    _, transcription_id_str = query.data.split(":")
    transcription_id = int(transcription_id_str)

    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, query.from_user.id, PLATFORM_TELEGRAM):
        return

    text = get_result_text(transcription.provider, transcription.result_json)
    if not text:
        logging.warning("send_as_text: no result text for transcription %s", transcription_id)
        await safe_reply_text(query.message, "❌ Не удалось получить текст")
        return

    show_improve = not has_refinement(transcription_id, "improve")
    show_timecodes = transcription.provider == PROVIDER_REPLICATE
    await safe_edit_message_reply_markup(query, reply_markup=make_send_as_text_keyboard(transcription_id, show_send_as_text=False, show_improve=show_improve, show_timecodes=show_timecodes))
    for i in range(0, len(text), _TG_MAX_LEN):
        sent = await _reply_chunk(query.message, text[i:i + _TG_MAX_LEN])
        if sent is None:
            # Stop instead of skipping ahead: a truncated tail is recoverable
            # by pressing the restored button, holes in the middle are not.
            await safe_edit_message_reply_markup(query, reply_markup=make_send_as_text_keyboard(transcription_id, show_send_as_text=True, show_improve=show_improve, show_timecodes=show_timecodes))
            await safe_reply_text(
                query.message,
                "⚠️ Не удалось отправить текст целиком\n\n"
                "Нажмите «Отправить текстом» ещё раз чуть позже",
            )
            return
