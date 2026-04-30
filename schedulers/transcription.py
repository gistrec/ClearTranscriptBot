"""Periodic scheduler for checking transcription statuses."""
import logging
import tempfile

import providers.replicate as replicate_provider
import providers.speechkit as speechkit_provider
import messengers.telegram as tg_sender
import messengers.max as max_sender
import messengers.common as sender

from pathlib import Path
from datetime import datetime

from telegram.ext import ContextTypes

from database.queries import change_user_balance, get_transcriptions_by_status, update_transcription

from utils.utils import format_duration, MoscowTimezone, SUMMARIZE_THRESHOLD, RATING_PROMPT
from utils.transcription import check_transcription, get_result
from utils.tg import need_edit, prune_edit_cache
from utils.s3 import upload_file
from utils.tokens import tokens_by_model
from utils.sentry import sentry_transaction, sentry_drop_transaction



@sentry_transaction(name="transcription.poll", op="task.check")
async def check_running_tasks(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Poll running transcriptions and send results when ready."""
    tasks = get_transcriptions_by_status("running")
    if not tasks:
        sentry_drop_transaction()
        return

    now = datetime.now(MoscowTimezone)

    prune_edit_cache(context, {task.id for task in tasks})

    for task in tasks:
        started_at = task.started_at.replace(tzinfo=MoscowTimezone)

        duration = int((now - started_at).total_seconds())
        duration_str = format_duration(duration)

        # Редактируем сообщение только если прошло достаточно времени
        if need_edit(context, task.id, now):
            audio_duration_str = format_duration(task.duration_seconds)
            status_text = (
                f"⏳ Распознавание в процессе\n\n"
                f"Длительность: {audio_duration_str}\n"
                f"Стоимость: {task.price_for_user} ₽\n\n"
                f"Время обработки: {duration_str}"
            )
            await sender.safe_edit_message(context, task.user_platform, task.user_id, task.message_id, status_text)

        try:
            result_info = await check_transcription(task.operation_id, provider=task.provider)
        except Exception:
            logging.exception("Failed to check transcription for task %s", task.id)
            continue

        # Результата еще нет, проверим снова через секунду
        if result_info is None:
            continue

        payload = result_info.get("payload") or {}
        predict_time = payload.get("predict_time")
        if result_info.get("provider") == "replicate" and predict_time:
            actual_price = replicate_provider.cost_in_rub(predict_time, task.model)
        else:
            actual_price = speechkit_provider.cost_in_rub(task.duration_seconds)

        update_transcription(
            task.id,
            result_json=payload,
            finished_at=now,
            actual_price=actual_price,
        )

        if not result_info.get("success"):
            logging.warning("Transcription failed task=%s payload=%s", task.id, payload)
            update_transcription(task.id, status="failed")
            change_user_balance(task.user_id, task.user_platform, task.price_for_user)  # Refund if failed
            fail_text = (
                "❌ Распознавание завершилось с ошибкой\n\n"
                "Попробуйте ещё раз"
            )
            await sender.safe_edit_message(context, task.user_platform, task.user_id, task.message_id, fail_text)
            continue

        text = get_result(result_info)
        token_counts = tokens_by_model(text)

        if not text:
            text = "(речь в записи отсутствует или слишком неразборчива для распознавания)"

        source_stem = Path(task.audio_s3_path).stem
        # Most filesystems cap filenames at 255 bytes; Cyrillic UTF-8 is 2 bytes/char,
        # so long Russian names overflow. Truncate stem to fit ".txt" suffix safely.
        encoded = source_stem.encode("utf-8")[:240]
        source_stem = encoded.decode("utf-8", errors="ignore") or "transcript"
        with tempfile.TemporaryDirectory() as workdir:
            path = Path(workdir) / f"{source_stem}.txt"
            path.write_text(text, encoding="utf-8")

            object_name = f"result/{task.user_id}/{path.name}"
            s3_url = await upload_file(path, object_name)
            if not s3_url:
                logging.warning("S3 upload failed task=%s object=%s", task.id, object_name)
                update_transcription(task.id, status="failed")
                change_user_balance(task.user_id, task.user_platform, task.price_for_user)  # Refund if upload failed
                fail_text = (
                    "❌ Распознавание завершилось с ошибкой\n\n"
                    "Попробуйте ещё раз"
                )
                await sender.safe_edit_message(context, task.user_platform, task.user_id, task.message_id, fail_text)
                continue

            audio_duration_str = format_duration(task.duration_seconds)

            # Build platform-specific action keyboard
            if task.duration_seconds > SUMMARIZE_THRESHOLD:
                tg_action_keyboard = tg_sender.make_summarize_keyboard(task.id)
                max_action_keyboard = max_sender.make_summarize_keyboard(task.id)
            else:
                tg_action_keyboard = tg_sender.make_send_as_text_keyboard(task.id)
                max_action_keyboard = max_sender.make_send_as_text_keyboard(task.id)

            done_text = (
                f"✅ Распознавание завершено\n\n"
                f"Длительность: {audio_duration_str}\n"
                f"Стоимость: {task.price_for_user} ₽\n\n"
                f"Время обработки: {duration_str}\n\n"
            )
            await sender.safe_edit_message(context, task.user_platform, task.user_id, task.message_id, done_text, tg_keyboard=tg_action_keyboard, max_keyboard=max_action_keyboard)

            try:
                tg_rating_keyboard = tg_sender.make_rating_keyboard(task.id)
                max_rating_keyboard = max_sender.make_rating_keyboard(task.id)

                await sender.safe_send_document(
                    context, task.user_platform, task.user_id, task.message_id,
                    text.encode("utf-8"), path.name, RATING_PROMPT,
                    tg_keyboard=tg_rating_keyboard, max_keyboard=max_rating_keyboard,
                )

                update_transcription(
                    task.id,
                    status="completed",
                    result_s3_path=s3_url,
                    llm_tokens_by_encoding=token_counts,
                )
            except Exception:
                logging.exception(f"Failed to send result for task {task.id}")
                update_transcription(
                    task.id,
                    status="failed",
                    result_s3_path=s3_url,
                    llm_tokens_by_encoding=token_counts,
                )
                change_user_balance(task.user_id, task.user_platform, task.price_for_user)  # Refund if sending failed
                fail_text = (
                    "❌ Распознавание завершилось с ошибкой\n\n"
                    "Попробуйте ещё раз"
                )
                await sender.safe_edit_message(context, task.user_platform, task.user_id, task.message_id, fail_text)
