"""Periodic scheduler for checking transcription statuses."""
import logging
import tempfile

import providers.replicate as replicate_provider
import providers.speechkit as speechkit_provider
import messengers.telegram as tg_sender
import messengers.max as max_sender
import messengers.common as sender
import utils.heartbeat as heartbeat

from pathlib import Path
from datetime import datetime

from telegram.ext import ContextTypes

from database.models import PROVIDER_REPLICATE, STATUS_RUNNING, STATUS_COMPLETED
from database.queries import fail_transcription_and_refund, get_transcriptions_by_status, update_transcription

from utils.utils import format_duration, MoscowTimezone, SUMMARIZE_THRESHOLD, RATING_PROMPT
from utils.transcription import check_transcription, get_result
from utils.tg import need_edit, prune_edit_cache
from utils.s3 import upload_file
from utils.tokens import tokens_by_model
from utils.sentry import sentry_transaction, sentry_drop_transaction


# Safety net only. A task with no result after this long is treated as hung and
# gets cancelled + refunded. Real jobs finish well under this even when
# Replicate's queue is backed up: the slowest successful job on record took
# ~86 min, almost entirely queue wait (the predict itself is seconds). Kept
# comfortably above that so we never cancel a job that would have succeeded.
MAX_PROCESSING_SECONDS = 2 * 60 * 60

# Once a task has run this long without a result, the periodic status message
# apologises for the unusual delay (Replicate's queue is backed up). The job
# still completes — this only manages the user's expectations.
DELAY_APOLOGY_SECONDS = 15 * 60

# A running task with no operation_id after this long is a zombie: the process
# died in create_task after charging the user but before recording the provider
# operation. It will never produce a result — fail it and refund. Normally that
# window lasts seconds; 10 minutes is far beyond any legitimate start delay.
ZOMBIE_SECONDS = 10 * 60


@sentry_transaction(name="transcription.poll", op="task.check")
async def check_running_tasks(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Poll running transcriptions and send results when ready."""
    heartbeat.beat("transcription")
    tasks = get_transcriptions_by_status(STATUS_RUNNING)
    if not tasks:
        sentry_drop_transaction()
        return

    now = datetime.now(MoscowTimezone)

    prune_edit_cache(context, {task.id for task in tasks})

    for task in tasks:
        started_at = task.started_at.replace(tzinfo=MoscowTimezone)

        # Normally just the brief window in create_task between the claim
        # (status='running') and operation_id being written — skip and wait.
        # If the window persists, the process died mid-create: reap the zombie.
        if task.operation_id is None:
            if (now - started_at).total_seconds() > ZOMBIE_SECONDS:
                logging.warning("Reaping zombie task=%s (charged, no operation_id)", task.id)
                if fail_transcription_and_refund(task.id, finished_at=now):
                    await sender.safe_edit_message(
                        context, task.user_platform, task.user_id, task.message_id,
                        "❌ Не удалось запустить распознавание\n\n"
                        "Деньги вернули на баланс, попробуйте ещё раз",
                    )
            continue

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
            if duration > DELAY_APOLOGY_SECONDS:
                status_text += (
                    "\n\nИзвините за задержку 🙏 Сейчас большая очередь, "
                    "обработка идёт дольше обычного — мы продолжаем работать "
                    "над вашим файлом, результат придёт."
                )
            await sender.safe_edit_message(context, task.user_platform, task.user_id, task.message_id, status_text)

        try:
            result_info = await check_transcription(task.operation_id, provider=task.provider)
        except Exception:
            logging.exception("Failed to check transcription for task %s", task.id)
            continue

        # Результата ещё нет
        if result_info is None:
            # Задача висит слишком долго (очередь провайдера перегружена) —
            # отменяем её, возвращаем деньги и просим повторить.
            if duration > MAX_PROCESSING_SECONDS:
                if task.provider == PROVIDER_REPLICATE:
                    await replicate_provider.cancel(task.operation_id)
                logging.warning("Cancelling stuck task=%s after %ss", task.id, duration)
                if fail_transcription_and_refund(task.id, finished_at=now):
                    timeout_text = (
                        "❌ Не удалось распознать — очередь обработки перегружена\n\n"
                        "Деньги вернули на баланс, попробуйте ещё раз"
                    )
                    await sender.safe_edit_message(context, task.user_platform, task.user_id, task.message_id, timeout_text)
            continue

        payload = result_info.get("payload") or {}
        predict_time = payload.get("predict_time")
        if result_info.get("provider") == PROVIDER_REPLICATE and predict_time:
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
            fail_transcription_and_refund(task.id)
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

        low_quality = (
            result_info.get("provider") == PROVIDER_REPLICATE
            and replicate_provider.looks_like_hallucination(payload)
        )

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
                fail_transcription_and_refund(task.id)
                fail_text = (
                    "❌ Распознавание завершилось с ошибкой\n\n"
                    "Попробуйте ещё раз"
                )
                await sender.safe_edit_message(context, task.user_platform, task.user_id, task.message_id, fail_text)
                continue

            audio_duration_str = format_duration(task.duration_seconds)

            # Build platform-specific action keyboard
            show_timecodes = task.provider == PROVIDER_REPLICATE
            if (task.duration_seconds or 0) > SUMMARIZE_THRESHOLD:
                tg_action_keyboard = tg_sender.make_summarize_keyboard(task.id, show_timecodes=show_timecodes)
                max_action_keyboard = max_sender.make_summarize_keyboard(task.id, show_timecodes=show_timecodes)
            else:
                tg_action_keyboard = tg_sender.make_send_as_text_keyboard(task.id, show_timecodes=show_timecodes)
                max_action_keyboard = max_sender.make_send_as_text_keyboard(task.id, show_timecodes=show_timecodes)

            done_text = (
                f"✅ Распознавание завершено\n\n"
                f"Длительность: {audio_duration_str}\n"
                f"Стоимость: {task.price_for_user} ₽\n\n"
                f"Время обработки: {duration_str}\n\n"
            )
            if low_quality:
                done_text += (
                    "⚠️ Запись похожа на зашумлённую или неразборчивую — "
                    "проверьте результат, распознавание может быть неточным\n\n"
                )
            # Persist final state before delivering the action keyboard so the
            # buttons (send-as-text / summarize / timecodes) see result_s3_path
            # the moment they become clickable.
            update_transcription(
                task.id,
                status=STATUS_COMPLETED,
                result_s3_path=s3_url,
                llm_tokens_by_encoding=token_counts,
            )
            await sender.safe_edit_message(context, task.user_platform, task.user_id, task.message_id, done_text, tg_keyboard=tg_action_keyboard, max_keyboard=max_action_keyboard)

            try:
                await sender.safe_send_document(
                    context, task.user_platform, task.user_id, task.message_id,
                    text.encode("utf-8"), path.name, "",
                )

                tg_rating_keyboard = tg_sender.make_rating_keyboard(task.id)
                max_rating_keyboard = max_sender.make_rating_keyboard(task.id)
                await sender.safe_send_message_with_keyboard(
                    context, task.user_platform, task.user_id,
                    RATING_PROMPT,
                    tg_keyboard=tg_rating_keyboard, max_keyboard=max_rating_keyboard,
                )
            except Exception:
                # Best-effort delivery: transcription succeeded and result lives
                # in S3 — user can re-fetch via the "Отправить текстом" button.
                logging.exception(f"Failed to deliver result for task {task.id}")
