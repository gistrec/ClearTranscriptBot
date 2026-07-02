"""Periodic scheduler for checking transcription statuses."""
import logging

import providers.replicate as replicate_provider
import providers.speechkit as speechkit_provider
import messengers.telegram as tg_sender
import messengers.max as max_sender
import messengers.common as sender
import utils.heartbeat as heartbeat

from pathlib import Path
from datetime import datetime

from telegram.ext import ContextTypes

from database.models import PROVIDER_REPLICATE, STATUS_RUNNING, STATUS_COMPLETED, STATUS_REJECTED
from database.queries import (
    fail_transcription_and_refund,
    get_transcriptions_by_status,
    get_user,
    has_other_completed_transcription,
    update_transcription,
)
from utils.marketing import track_goal

from utils.utils import format_duration, MoscowTimezone, SUMMARIZE_THRESHOLD, INLINE_MAX_CHARS, RATING_PROMPT
from utils.transcription import check_transcription, get_result
from utils.tg import need_edit, prune_edit_cache
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
                f"⏳ Расшифровываем запись…\n\n"
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
                "Деньги вернули на баланс, попробуйте ещё раз"
            )
            await sender.safe_edit_message(context, task.user_platform, task.user_id, task.message_id, fail_text, bold_header=True)
            continue

        text = get_result(result_info)
        token_counts = tokens_by_model(text)

        # Wrong-language detection needs the real text (before any fallback):
        # an empty result is "no speech", not "wrong language".
        wrong_language = bool(
            text
            and result_info.get("provider") == PROVIDER_REPLICATE
            and replicate_provider.is_wrong_language(payload)
        )

        # Output the user must not pay for: no discernible speech, or garbled /
        # looping recognition. Wrong language is excluded — it gets a free
        # re-transcribe, which is more useful than a refund. Refund and stop:
        # there is nothing worth delivering.
        hallucinated = (
            not wrong_language
            and result_info.get("provider") == PROVIDER_REPLICATE
            and replicate_provider.looks_like_hallucination(payload)
        )
        if not text or hallucinated:
            refund_text = (
                "🔇 В записи не нашлось разборчивой речи\n\n"
                "Деньги вернули на баланс"
                if not text else
                "😕 Запись слишком зашумлённая или неразборчивая — распознать не удалось\n\n"
                "Деньги вернули на баланс"
            )
            fail_transcription_and_refund(task.id, status=STATUS_REJECTED, finished_at=now)
            await sender.safe_edit_message(context, task.user_platform, task.user_id, task.message_id, refund_text, bold_header=True)
            continue

        source_stem = Path(task.audio_s3_path).stem
        # Most filesystems cap filenames at 255 bytes; Cyrillic UTF-8 is 2 bytes/char,
        # so long Russian names overflow. Truncate stem to fit ".txt" suffix safely.
        encoded = source_stem.encode("utf-8")[:240]
        source_stem = encoded.decode("utf-8", errors="ignore") or "transcript"
        filename = f"{source_stem}.txt"

        audio_duration_str = format_duration(task.duration_seconds)

        # Short results go straight into the chat as text — a .txt file for a
        # couple of sentences is the friction users complained about. The cap
        # stays under the 4000 Max / 4096 Telegram message limit with room to
        # spare. Wrong-language output stays a file: it is garbage the user
        # will re-transcribe, not read inline.
        inline = not wrong_language and len(text) <= INLINE_MAX_CHARS

        # Build platform-specific action keyboard
        show_timecodes = task.provider == PROVIDER_REPLICATE
        if wrong_language:
            # Garbage in the wrong language — the only useful action is a
            # free re-transcribe, so offer the language picker instead.
            tg_action_keyboard = tg_sender.make_language_retry_keyboard(task.id)
            max_action_keyboard = max_sender.make_language_retry_keyboard(task.id)
        elif (task.duration_seconds or 0) > SUMMARIZE_THRESHOLD:
            tg_action_keyboard = tg_sender.make_summarize_keyboard(task.id, show_timecodes=show_timecodes)
            max_action_keyboard = max_sender.make_summarize_keyboard(task.id, show_timecodes=show_timecodes)
        else:
            # Inlined text makes the "Отправить текстом" button redundant.
            tg_action_keyboard = tg_sender.make_send_as_text_keyboard(task.id, show_send_as_text=not inline, show_timecodes=show_timecodes)
            max_action_keyboard = max_sender.make_send_as_text_keyboard(task.id, show_send_as_text=not inline, show_timecodes=show_timecodes)

        done_text = (
            f"✅ Распознавание завершено\n\n"
            f"Длительность: {audio_duration_str}\n"
            f"Стоимость: {task.price_for_user} ₽\n\n"
            f"Время обработки: {duration_str}\n\n"
        )
        if wrong_language:
            done_text += (
                "🌐 Похоже, язык распознан неверно. Если запись на другом "
                "языке — распознайте её заново бесплатно, выбрав язык ниже\n\n"
            )
        # Persist final state before delivering the action keyboard so the
        # buttons (send-as-text / summarize / timecodes) find a usable result
        # the moment they become clickable. The text is served from result_json,
        # so there is no S3 copy to record.
        update_transcription(
            task.id,
            status=STATUS_COMPLETED,
            llm_tokens_by_encoding=token_counts,
        )
        if not has_other_completed_transcription(task.user_id, task.user_platform, task.id):
            user = get_user(task.user_id, task.user_platform)
            if user is not None and user.yclid:
                context.application.create_task(
                    track_goal(user.yclid, f"{task.user_platform}_first_transcription")
                )
        await sender.safe_edit_message(context, task.user_platform, task.user_id, task.message_id, done_text, tg_keyboard=tg_action_keyboard, max_keyboard=max_action_keyboard, bold_header=True)

        try:
            if inline:
                await sender.safe_send_message(
                    context, task.user_platform, task.user_id, text,
                )
            else:
                await sender.safe_send_document(
                    context, task.user_platform, task.user_id, task.message_id,
                    text.encode("utf-8"), filename, "",
                )

            tg_rating_keyboard = tg_sender.make_rating_keyboard(task.id)
            max_rating_keyboard = max_sender.make_rating_keyboard(task.id)
            await sender.safe_send_message_with_keyboard(
                context, task.user_platform, task.user_id,
                RATING_PROMPT,
                tg_keyboard=tg_rating_keyboard, max_keyboard=max_rating_keyboard,
            )
        except Exception:
            # Best-effort delivery: transcription succeeded and the text lives
            # in result_json — user can re-fetch via the "Отправить текстом" button.
            logging.exception(f"Failed to deliver result for task {task.id}")
