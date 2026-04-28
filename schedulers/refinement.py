"""Periodic scheduler for checking refinement statuses."""
import logging

import messengers.common as sender

from datetime import datetime

from telegram.ext import ContextTypes

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
    for record in pending_refinements:
        fail_text = "❌ Не удалось улучшить текст" if record.task_type == "improve" else "❌ Не удалось создать конспект"

        transcription = get_transcription(record.transcription_id)
        if transcription is None or not transcription.result_s3_path:
            update_refinement(record.id, status="failed", finished_at=datetime.now(MoscowTimezone))
            await sender.safe_edit_message(context, record.user_platform, record.user_id, record.message_id, fail_text)
            continue

        object_name = object_name_from_url(transcription.result_s3_path)
        text = await download_text(object_name)
        if not text:
            update_refinement(record.id, status="failed", finished_at=datetime.now(MoscowTimezone))
            await sender.safe_edit_message(context, record.user_platform, record.user_id, record.message_id, fail_text)
            continue

        operation_id = await start_refinement(text, task_type=record.task_type)
        if not operation_id:
            update_refinement(record.id, status="failed", finished_at=datetime.now(MoscowTimezone))
            await sender.safe_edit_message(context, record.user_platform, record.user_id, record.message_id, fail_text)
            continue

        update_refinement(
            record.id,
            status="running",
            operation_id=operation_id,
            llm_model=REPLICATE_LLM_MODEL,
        )


async def _process_running(context: ContextTypes.DEFAULT_TYPE, running_refinements) -> None:
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

        is_improve = record.task_type == "improve"
        in_progress_text = "⏳ Улучшаю текст..." if is_improve else "⏳ Создаю конспект..."
        fail_text = "❌ Не удалось улучшить текст" if is_improve else "❌ Не удалось создать конспект"

        if result is None:
            if need_edit(context, record.id, now, cache_key="refinement_status_cache"):
                elapsed = int((now - record.created_at.replace(tzinfo=MoscowTimezone)).total_seconds())
                elapsed_str = format_duration(elapsed)
                await sender.safe_edit_message(
                    context, record.user_platform, record.user_id, record.message_id,
                    f"{in_progress_text}\n\nВремя обработки: {elapsed_str}",
                )
            continue

        if not result["success"]:
            update_refinement(record.id, status="failed", finished_at=now)
            await sender.safe_edit_message(context, record.user_platform, record.user_id, record.message_id, fail_text)
            continue

        update_refinement(record.id, status="completed", result_text=result["text"], finished_at=now)

        if is_improve:
            await sender.safe_edit_message(context, record.user_platform, record.user_id, record.message_id, "✨ Текст улучшен")
            await sender.safe_send_document(context, record.user_platform, record.user_id, None, result["text"].encode("utf-8"), "improved.txt", "")
        else:
            message = "📝 Конспект\n\n" + result["text"]
            # Telegram message limit is 4096 characters
            if len(message) > 4096:
                message = message[:4093] + "..."
            await sender.safe_edit_message(context, record.user_platform, record.user_id, record.message_id, message)
