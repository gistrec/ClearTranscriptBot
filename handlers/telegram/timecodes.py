"""Handlers for the 'С таймкодами' button on completed Replicate transcriptions."""
import logging

from pathlib import Path

from telegram import InputFile, Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM, is_owner
from database.queries import get_transcription, has_refinement
from utils.sentry import sentry_bind_user, sentry_transaction
from utils.utils import SUMMARIZE_THRESHOLD
from utils.timecodes import FORMATTERS, extract_segments, parse_result_json
from messengers.telegram import (
    make_send_as_text_keyboard,
    make_summarize_keyboard,
    make_timecodes_format_keyboard,
    safe_edit_message_reply_markup,
    safe_query_answer,
    safe_reply_text,
    safe_send_document,
)


def _restore_main_keyboard(transcription):
    show_summarize = not has_refinement(transcription.id, "summarize")
    show_improve = not has_refinement(transcription.id, "improve")
    if (transcription.duration_seconds or 0) > SUMMARIZE_THRESHOLD:
        return make_summarize_keyboard(transcription.id, show_summarize=show_summarize, show_improve=show_improve, show_timecodes=True)
    return make_send_as_text_keyboard(transcription.id, show_improve=show_improve, show_timecodes=True)


@sentry_bind_user
@sentry_transaction(name="timecodes.open", op="telegram.callback")
async def handle_timecodes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_query_answer(query)

    _, transcription_id_str = query.data.split(":")
    transcription_id = int(transcription_id_str)

    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, query.from_user.id, PLATFORM_TELEGRAM):
        return
    if transcription.provider != "replicate":
        return

    await safe_edit_message_reply_markup(query, reply_markup=make_timecodes_format_keyboard(transcription_id))


@sentry_bind_user
@sentry_transaction(name="timecodes.back", op="telegram.callback")
async def handle_timecodes_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_query_answer(query)

    _, transcription_id_str = query.data.split(":")
    transcription_id = int(transcription_id_str)

    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, query.from_user.id, PLATFORM_TELEGRAM):
        return

    await safe_edit_message_reply_markup(query, reply_markup=_restore_main_keyboard(transcription))


@sentry_bind_user
@sentry_transaction(name="timecodes.send", op="telegram.callback")
async def handle_timecodes_format(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_query_answer(query)

    _, transcription_id_str, fmt = query.data.split(":")
    transcription_id = int(transcription_id_str)

    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, query.from_user.id, PLATFORM_TELEGRAM):
        return
    if transcription.provider != "replicate":
        return

    formatter_entry = FORMATTERS.get(fmt)
    if formatter_entry is None:
        return
    formatter, extension = formatter_entry

    payload = parse_result_json(transcription.result_json)
    if payload is None:
        await safe_reply_text(query.message, "Не удалось получить таймкоды для этой расшифровки")
        return

    segments = extract_segments(payload)
    if not segments:
        await safe_reply_text(query.message, "В этой расшифровке нет данных с таймкодами")
        return

    text = formatter(segments)
    stem = Path(transcription.audio_s3_path or "transcript").stem
    encoded = stem.encode("utf-8")[:240]
    stem = encoded.decode("utf-8", errors="ignore") or "transcript"
    filename = f"{stem}.{extension}"

    sent = await safe_send_document(
        context.bot,
        query.message.chat_id,
        query.message.message_id,
        InputFile(text.encode("utf-8"), filename=filename),
        "",
    )
    if sent is None:
        logging.warning("timecodes: failed to send document for transcription %s", transcription_id)
        await safe_reply_text(query.message, "Не удалось отправить файл")
        return

    await safe_edit_message_reply_markup(query, reply_markup=_restore_main_keyboard(transcription))
