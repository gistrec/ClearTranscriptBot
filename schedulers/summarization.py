"""Periodic scheduler for checking summarization statuses."""
import logging

from datetime import datetime

from telegram.ext import ContextTypes

from database.queries import (
    get_summarization,
    get_summarizations_by_status,
    get_transcription,
    update_summarization,
)
from utils.s3 import download_text, object_name_from_url
from utils.summarize import REPLICATE_LLM_MODEL, check_summarization, start_summarization
from utils.tg import need_edit
from utils.utils import MoscowTimezone, format_duration


async def check_summarizations(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pick up pending summarizations and poll running ones."""
    await _process_pending(context)
    await _process_running(context)


async def _process_pending(context: ContextTypes.DEFAULT_TYPE) -> None:
    sender = context.bot_data.get("sender")
    for record in get_summarizations_by_status("pending"):
        transcription = get_transcription(record.transcription_id)
        if transcription is None or not transcription.result_s3_path:
            update_summarization(record.id, status="failed", finished_at=datetime.now(MoscowTimezone))
            await _edit_status(context, sender, record.user_platform, record.user_id, record.message_id, "❌ Не удалось создать конспект")
            continue

        object_name = object_name_from_url(transcription.result_s3_path)
        text = await download_text(object_name)
        if not text:
            update_summarization(record.id, status="failed", finished_at=datetime.now(MoscowTimezone))
            await _edit_status(context, sender, record.user_platform, record.user_id, record.message_id, "❌ Не удалось создать конспект")
            continue

        operation_id = await start_summarization(text)
        if not operation_id:
            update_summarization(record.id, status="failed", finished_at=datetime.now(MoscowTimezone))
            await _edit_status(context, sender, record.user_platform, record.user_id, record.message_id, "❌ Не удалось создать конспект")
            continue

        update_summarization(
            record.id,
            status="running",
            operation_id=operation_id,
            llm_model=REPLICATE_LLM_MODEL,
        )


async def _process_running(context: ContextTypes.DEFAULT_TYPE) -> None:
    sender = context.bot_data.get("sender")
    for record in get_summarizations_by_status("running"):
        # Re-fetch to get latest operation_id (set during pending→running transition)
        record = get_summarization(record.id)
        if record is None:
            continue

        now = datetime.now(MoscowTimezone)

        result = await check_summarization(record.operation_id)
        if result is None:
            if need_edit(context, record.id, now, cache_key="summarization_status_cache"):
                elapsed = int((now - record.created_at.replace(tzinfo=MoscowTimezone)).total_seconds())
                elapsed_str = format_duration(elapsed)
                await _edit_status(
                    context, sender, record.user_platform, record.user_id, record.message_id,
                    f"⏳ Создаю конспект...\n\nВремя обработки: {elapsed_str}",
                )
            continue

        if not result["success"]:
            update_summarization(record.id, status="failed", finished_at=now)
            await _edit_status(context, sender, record.user_platform, record.user_id, record.message_id, "❌ Не удалось создать конспект")
            continue

        message = f"📝 Конспект:\n\n{result['text']}"
        # Telegram message limit is 4096 characters
        if len(message) > 4096:
            message = message[:4093] + "..."

        update_summarization(record.id, status="completed", result_text=result["text"], finished_at=now)
        await _edit_status(context, sender, record.user_platform, record.user_id, record.message_id, message)


async def _edit_status(
    context: ContextTypes.DEFAULT_TYPE,
    sender,
    platform: str,
    user_id: int,
    message_id,
    text: str,
) -> None:
    if sender is not None:
        await sender.edit_message(platform, user_id, message_id, text)
    else:
        try:
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=int(message_id),
                text=text,
            )
        except Exception:
            logging.exception(f"Failed to edit summarization status message {message_id}")
