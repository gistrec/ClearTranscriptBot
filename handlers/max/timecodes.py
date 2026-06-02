"""Handlers for the 'С таймкодами' callbacks on Max messenger."""
import logging

from pathlib import Path

import aiomax

from database.models import PLATFORM_MAX, is_owner
from database.queries import get_transcription, has_refinement
from utils.sentry import sentry_bind_user_max, sentry_transaction
from utils.utils import SUMMARIZE_THRESHOLD
from utils.timecodes import FORMATTERS, extract_segments, parse_result_json
from messengers.max import (
    make_send_as_text_keyboard,
    make_summarize_keyboard,
    make_timecodes_format_keyboard,
    safe_callback_answer,
    safe_edit_message,
    safe_send_document,
    safe_send_message,
)


def _restore_main_keyboard(transcription):
    show_summarize = not has_refinement(transcription.id, "summarize")
    show_improve = not has_refinement(transcription.id, "improve")
    if (transcription.duration_seconds or 0) > SUMMARIZE_THRESHOLD:
        return make_summarize_keyboard(transcription.id, show_summarize=show_summarize, show_improve=show_improve, show_timecodes=True)
    return make_send_as_text_keyboard(transcription.id, show_improve=show_improve, show_timecodes=True)


@sentry_bind_user_max
@sentry_transaction(name="timecodes.open", op="max.callback")
async def handle_max_timecodes(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await safe_callback_answer(callback, notification="")

    try:
        _, transcription_id_str = callback.payload.split(":")
        transcription_id = int(transcription_id_str)
        user_id = int(callback.user.user_id)
    except (ValueError, AttributeError):
        logging.warning("Max timecodes: cannot parse callback payload: %s", callback.payload)
        return

    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, user_id, PLATFORM_MAX):
        return
    if transcription.provider != "replicate":
        return

    message_id = callback.message.body.message_id
    await safe_edit_message(bot, message_id, callback.message.body.text or "", keyboard=make_timecodes_format_keyboard(transcription_id))


@sentry_bind_user_max
@sentry_transaction(name="timecodes.back", op="max.callback")
async def handle_max_timecodes_back(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await safe_callback_answer(callback, notification="")

    try:
        _, transcription_id_str = callback.payload.split(":")
        transcription_id = int(transcription_id_str)
        user_id = int(callback.user.user_id)
    except (ValueError, AttributeError):
        logging.warning("Max timecodes_back: cannot parse callback payload: %s", callback.payload)
        return

    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, user_id, PLATFORM_MAX):
        return

    message_id = callback.message.body.message_id
    await safe_edit_message(bot, message_id, callback.message.body.text or "", keyboard=_restore_main_keyboard(transcription))


@sentry_bind_user_max
@sentry_transaction(name="timecodes.send", op="max.callback")
async def handle_max_timecodes_format(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await safe_callback_answer(callback, notification="")

    try:
        _, transcription_id_str, fmt = callback.payload.split(":")
        transcription_id = int(transcription_id_str)
        user_id = int(callback.user.user_id)
    except (ValueError, AttributeError):
        logging.warning("Max timecodes_format: cannot parse callback payload: %s", callback.payload)
        return

    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, user_id, PLATFORM_MAX):
        return
    if transcription.provider != "replicate":
        return

    formatter_entry = FORMATTERS.get(fmt)
    if formatter_entry is None:
        return
    formatter, extension = formatter_entry

    chat_id = callback.message.recipient.chat_id
    message_id = callback.message.body.message_id

    payload = parse_result_json(transcription.result_json)
    if payload is None:
        await safe_send_message(bot, "Не удалось получить таймкоды для этой расшифровки", chat_id=chat_id)
        return

    segments = extract_segments(payload)
    if not segments:
        await safe_send_message(bot, "В этой расшифровке нет данных с таймкодами", chat_id=chat_id)
        return

    text = formatter(segments)
    stem = Path(transcription.audio_s3_path or "transcript").stem
    encoded = stem.encode("utf-8")[:240]
    stem = encoded.decode("utf-8", errors="ignore") or "transcript"
    filename = f"{stem}.{extension}"

    sent = await safe_send_document(bot, chat_id, text.encode("utf-8"), filename, "")
    if sent is None:
        await safe_send_message(bot, "Не удалось отправить файл", chat_id=chat_id)
        return

    await safe_edit_message(bot, message_id, callback.message.body.text or "", keyboard=_restore_main_keyboard(transcription))
