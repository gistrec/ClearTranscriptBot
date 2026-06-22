"""Handlers for re-transcribing a recording in a chosen language (Max)."""
import logging
from decimal import Decimal
from datetime import datetime

import aiomax

from database.models import (
    PLATFORM_MAX,
    PROVIDER_REPLICATE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    is_owner,
)
from database.queries import add_transcription, get_transcription, update_transcription

from messengers.max import (
    make_language_other_keyboard,
    make_language_retry_keyboard,
    safe_callback_answer,
    safe_edit_message,
)
from utils.sentry import sentry_bind_user_max, sentry_transaction
from utils.transcription import get_model_name, start_transcription
from utils.utils import MoscowTimezone, RETRY_LANGUAGE_NAMES


def _parse(callback: aiomax.Callback):
    """Return (transcription_id, user_id, language|None) from the payload."""
    parts = callback.payload.split(":")
    transcription_id = int(parts[1])
    user_id = int(callback.user.user_id)
    language = parts[2] if len(parts) > 2 else None
    return transcription_id, user_id, language


@sentry_bind_user_max
@sentry_transaction(name="retranscribe.more", op="max.callback")
async def handle_max_retranscribe_more(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await safe_callback_answer(callback, notification="")
    try:
        transcription_id, user_id, _ = _parse(callback)
    except (ValueError, AttributeError, IndexError):
        logging.warning("Max retranscribe_more: cannot parse payload: %s", callback.payload)
        return

    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, user_id, PLATFORM_MAX):
        return

    message_id = callback.message.body.message_id
    await safe_edit_message(
        bot, message_id, callback.message.body.text or "",
        keyboard=make_language_other_keyboard(transcription_id),
    )


@sentry_bind_user_max
@sentry_transaction(name="retranscribe.back", op="max.callback")
async def handle_max_retranscribe_back(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await safe_callback_answer(callback, notification="")
    try:
        transcription_id, user_id, _ = _parse(callback)
    except (ValueError, AttributeError, IndexError):
        logging.warning("Max retranscribe_back: cannot parse payload: %s", callback.payload)
        return

    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, user_id, PLATFORM_MAX):
        return

    message_id = callback.message.body.message_id
    await safe_edit_message(
        bot, message_id, callback.message.body.text or "",
        keyboard=make_language_retry_keyboard(transcription_id),
    )


@sentry_bind_user_max
@sentry_transaction(name="retranscribe.start", op="max.callback")
async def handle_max_retranscribe(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await safe_callback_answer(callback, notification="")
    try:
        transcription_id, user_id, language = _parse(callback)
    except (ValueError, AttributeError, IndexError):
        logging.warning("Max retranscribe: cannot parse payload: %s", callback.payload)
        return
    if language is None:
        return

    source = get_transcription(transcription_id)
    if not is_owner(source, user_id, PLATFORM_MAX):
        return
    if source.provider != PROVIDER_REPLICATE:
        return

    message_id = callback.message.body.message_id
    now = datetime.now(MoscowTimezone)
    model = get_model_name(source.provider, source.duration_seconds)

    # Free retry: WhisperX guessed the language wrong on our side, so the user
    # pays nothing (price_for_user=0). Insert as pending — the scheduler ignores
    # pending rows — and only flip to running once the provider job exists, fully
    # populated, so the poller never sees a half-started task.
    retry = add_transcription(
        user_id=source.user_id,
        platform=PLATFORM_MAX,
        status=STATUS_PENDING,
        audio_s3_path=source.audio_s3_path,
        provider=source.provider,
        duration_seconds=source.duration_seconds,
        mean_volume_db=source.mean_volume_db,
        price_for_user=Decimal("0"),
    )

    operation_id = await start_transcription(
        source.audio_s3_path,
        provider=source.provider,
        duration_seconds=source.duration_seconds,
        mean_volume_db=source.mean_volume_db,
        language=language,
    )
    if not operation_id:
        update_transcription(retry.id, status=STATUS_FAILED, finished_at=now)
        await safe_edit_message(
            bot, message_id,
            "❌ Не удалось запустить распознавание заново\n\n"
            "Попробуйте ещё раз чуть позже",
            attachments=[],
        )
        return

    update_transcription(
        retry.id,
        status=STATUS_RUNNING,
        started_at=now,
        model=model,
        message_id=str(message_id),
        operation_id=operation_id,
    )

    language_name = RETRY_LANGUAGE_NAMES.get(language, language)
    await safe_edit_message(
        bot, message_id,
        f"⏳ Распознаём заново на языке: {language_name}…\n\n"
        "Результат придёт следующим сообщением",
        attachments=[],
    )
