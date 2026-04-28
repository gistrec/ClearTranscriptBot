"""Periodic scheduler for checking refinement statuses."""
import logging

import messengers.telegram as tg_sender
import messengers.max as max_sender

from datetime import datetime

from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM
from database.queries import (
    get_refinement,
    get_refinements_by_status,
    get_transcription,
    update_refinement,
)
from utils.s3 import download_text, object_name_from_url
from utils.summarize import REPLICATE_LLM_MODEL, check_refinement, start_refinement
from utils.tg import need_edit, prune_edit_cache
from utils.utils import MoscowTimezone, format_duration
from utils.sentry import sentry_transaction, sentry_drop_transaction


@sentry_transaction(name="refinement.poll", op="task.check")
async def check_refinements(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pick up pending refinements and poll running ones."""
    pending_refinements = get_refinements_by_status("pending")
    running_refinements = get_refinements_by_status("running")
    if not pending_refinements and not running_refinements:
        sentry_drop_transaction()
        return

    prune_edit_cache(context, {r.id for r in running_refinements}, cache_key="refinement_status_cache")

    await _process_pending(context, pending_refinements)
    await _process_running(context, running_refinements)


async def _process_pending(context: ContextTypes.DEFAULT_TYPE, pending_refinements) -> None:
    max_bot = context.bot_data.get("max_bot")
    for record in pending_refinements:
        transcription = get_transcription(record.transcription_id)
        if transcription is None or not transcription.result_s3_path:
            update_refinement(record.id, status="failed", finished_at=datetime.now(MoscowTimezone))
            await _edit_status(context, max_bot, record.user_platform, record.user_id, record.message_id, "❌ Не удалось создать конспект")
            continue

        object_name = object_name_from_url(transcription.result_s3_path)
        text = await download_text(object_name)
        if not text:
            update_refinement(record.id, status="failed", finished_at=datetime.now(MoscowTimezone))
            await _edit_status(context, max_bot, record.user_platform, record.user_id, record.message_id, "❌ Не удалось создать конспект")
            continue

        operation_id = await start_refinement(text)
        if not operation_id:
            update_refinement(record.id, status="failed", finished_at=datetime.now(MoscowTimezone))
            await _edit_status(context, max_bot, record.user_platform, record.user_id, record.message_id, "❌ Не удалось создать конспект")
            continue

        update_refinement(
            record.id,
            status="running",
            operation_id=operation_id,
            llm_model=REPLICATE_LLM_MODEL,
        )


async def _process_running(context: ContextTypes.DEFAULT_TYPE, running_refinements) -> None:
    max_bot = context.bot_data.get("max_bot")
    for record in running_refinements:
        # Re-fetch to get latest operation_id (set during pending→running transition)
        record = get_refinement(record.id)
        if record is None:
            continue

        now = datetime.now(MoscowTimezone)

        try:
            result = await check_refinement(record.operation_id)
        except Exception:
            logging.exception("Failed to check refinement for record %s", record.id)
            continue

        if result is None:
            if need_edit(context, record.id, now, cache_key="refinement_status_cache"):
                elapsed = int((now - record.created_at.replace(tzinfo=MoscowTimezone)).total_seconds())
                elapsed_str = format_duration(elapsed)
                await _edit_status(
                    context, max_bot, record.user_platform, record.user_id, record.message_id,
                    f"⏳ Создаю конспект...\n\n"
                    f"Время обработки: {elapsed_str}",
                )
            continue

        if not result["success"]:
            update_refinement(record.id, status="failed", finished_at=now)
            await _edit_status(context, max_bot, record.user_platform, record.user_id, record.message_id, "❌ Не удалось создать конспект")
            continue

        message = (
            "📝 Конспект\n\n"
            + result['text']
        )
        # Telegram message limit is 4096 characters
        if len(message) > 4096:
            message = message[:4093] + "..."

        update_refinement(record.id, status="completed", result_text=result["text"], finished_at=now)
        await _edit_status(context, max_bot, record.user_platform, record.user_id, record.message_id, message)


async def _edit_status(
    context: ContextTypes.DEFAULT_TYPE,
    max_bot,
    platform: str,
    user_id: int,
    message_id,
    text: str,
) -> None:
    if platform == PLATFORM_TELEGRAM:
        await tg_sender.safe_edit_message(context.bot, user_id, message_id, text)
    elif max_bot is not None:
        await max_sender.safe_edit_message(max_bot, str(message_id), text, attachments=[])
