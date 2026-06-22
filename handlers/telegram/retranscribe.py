"""Handlers for re-transcribing a recording in a chosen language."""
from decimal import Decimal
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from database.models import (
    PLATFORM_TELEGRAM,
    PROVIDER_REPLICATE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    is_owner,
)
from database.queries import add_transcription, get_transcription, update_transcription

from messengers.telegram import (
    make_language_other_keyboard,
    make_language_retry_keyboard,
    safe_edit_message_reply_markup,
    safe_edit_message_text,
    safe_query_answer,
)
from utils.sentry import sentry_bind_user, sentry_transaction
from utils.transcription import get_model_name, start_transcription
from utils.utils import MoscowTimezone, RETRY_LANGUAGE_NAMES


@sentry_bind_user
@sentry_transaction(name="retranscribe.more", op="telegram.callback")
async def handle_retranscribe_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_query_answer(query)

    _, id_str = query.data.split(":", 1)
    transcription_id = int(id_str)

    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, query.from_user.id, PLATFORM_TELEGRAM):
        return

    await safe_edit_message_reply_markup(query, reply_markup=make_language_other_keyboard(transcription_id))


@sentry_bind_user
@sentry_transaction(name="retranscribe.back", op="telegram.callback")
async def handle_retranscribe_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_query_answer(query)

    _, id_str = query.data.split(":", 1)
    transcription_id = int(id_str)

    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, query.from_user.id, PLATFORM_TELEGRAM):
        return

    await safe_edit_message_reply_markup(query, reply_markup=make_language_retry_keyboard(transcription_id))


@sentry_bind_user
@sentry_transaction(name="retranscribe.start", op="telegram.callback")
async def handle_retranscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_query_answer(query)

    _, id_str, language = query.data.split(":")
    transcription_id = int(id_str)

    source = get_transcription(transcription_id)
    if not is_owner(source, query.from_user.id, PLATFORM_TELEGRAM):
        return
    if source.provider != PROVIDER_REPLICATE:
        return

    now = datetime.now(MoscowTimezone)
    model = get_model_name(source.provider, source.duration_seconds)

    # Free retry: WhisperX guessed the language wrong on our side, so the user
    # pays nothing (price_for_user=0). Insert as pending — the scheduler ignores
    # pending rows — and only flip to running once the provider job exists, fully
    # populated, so the poller never sees a half-started task.
    retry = add_transcription(
        user_id=source.user_id,
        platform=PLATFORM_TELEGRAM,
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
        await safe_edit_message_text(
            query,
            "❌ Не удалось запустить распознавание заново\n\n"
            "Попробуйте ещё раз чуть позже",
        )
        return

    update_transcription(
        retry.id,
        status=STATUS_RUNNING,
        started_at=now,
        model=model,
        message_id=str(query.message.message_id),
        operation_id=operation_id,
    )

    language_name = RETRY_LANGUAGE_NAMES.get(language, language)
    await safe_edit_message_text(
        query,
        f"⏳ Распознаём заново на языке: {language_name}…\n\n"
        "Результат придёт следующим сообщением",
    )
