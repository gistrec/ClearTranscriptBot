"""Periodic scheduler for checking transcription statuses."""
import logging
import tempfile

import providers.replicate as replicate_provider
import providers.speechkit as speechkit_provider

from pathlib import Path
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database.models import PLATFORM_MAX
from database.queries import change_user_balance, get_transcriptions_by_status, update_transcription

from handlers.telegram.rate_transcription import make_rating_keyboard, RATING_PROMPT
from handlers.telegram.summarize import SUMMARIZE_THRESHOLD

from utils.utils import format_duration, MoscowTimezone
from utils.transcription import check_transcription, get_result
from utils.tg import need_edit, safe_edit_message_text, prune_edit_cache
from utils.s3 import upload_file
from utils.tokens import tokens_by_model
from utils.sentry import sentry_transaction, sentry_drop_transaction


def _make_max_summarize_keyboard(task_id: int):
    try:
        from aiomax.buttons import CallbackButton, KeyboardBuilder
        return KeyboardBuilder().row(CallbackButton("📝 Создать конспект", f"summarize:{task_id}"))
    except Exception:
        return None


def _make_max_send_as_text_keyboard(task_id: int):
    try:
        from aiomax.buttons import CallbackButton, KeyboardBuilder
        return KeyboardBuilder().row(CallbackButton("📄 Отправить текстом", f"send_as_text:{task_id}"))
    except Exception:
        return None


def _make_max_rating_keyboard(transcription_id: int):
    try:
        from aiomax.buttons import CallbackButton, KeyboardBuilder
        buttons = [CallbackButton(f"{i}⭐", f"rate:{transcription_id}:{i}") for i in range(1, 6)]
        return KeyboardBuilder().row(*buttons)
    except Exception:
        return None


@sentry_transaction(name="transcription.poll", op="task.check")
async def check_running_tasks(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Poll running transcriptions and send results when ready."""
    tasks = get_transcriptions_by_status("running")
    if not tasks:
        sentry_drop_transaction()
        return

    sender = context.bot_data.get("sender")
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
                f"⏳ Задача в работе\n\n"
                f"Длительность: {audio_duration_str}\n"
                f"Стоимость: {task.price_for_user} ₽\n\n"
                f"Время обработки: {duration_str}"
            )
            if sender is not None:
                await sender.edit_message(task.user_platform, task.user_id, task.message_id, status_text)
            else:
                await safe_edit_message_text(
                    context.bot, task.user_id, task.message_id, status_text
                )

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
            update_transcription(task.id, status="failed")
            change_user_balance(task.user_id, task.user_platform, task.price_for_user)  # Refund if failed
            fail_text = (
            "❌ Задача завершилась с ошибкой\n\n"
            "Попробуйте ещё раз"
        )
            if sender is not None:
                await sender.edit_message(task.user_platform, task.user_id, task.message_id, fail_text)
            else:
                await safe_edit_message_text(context.bot, task.user_id, task.message_id, fail_text)
            continue

        text = get_result(result_info)
        token_counts = tokens_by_model(text)

        if not text:
            text = "(речь в записи отсутствует или слишком неразборчива для распознавания)"

        source_stem = Path(task.audio_s3_path).stem
        tmp_dir = Path(tempfile.mkdtemp())
        path = tmp_dir / f"{source_stem}.txt"
        path.write_text(text, encoding="utf-8")

        object_name = f"result/{task.user_id}/{path.name}"
        s3_url = await upload_file(path, object_name)
        if not s3_url:
            update_transcription(task.id, status="failed")
            change_user_balance(task.user_id, task.user_platform, task.price_for_user)  # Refund if upload failed
            fail_text = (
            "❌ Задача завершилась с ошибкой\n\n"
            "Попробуйте ещё раз"
        )
            if sender is not None:
                await sender.edit_message(task.user_platform, task.user_id, task.message_id, fail_text)
            else:
                await safe_edit_message_text(context.bot, task.user_id, task.message_id, fail_text)
            path.unlink(missing_ok=True)
            tmp_dir.rmdir()
            continue

        audio_duration_str = format_duration(task.duration_seconds)

        # Build platform-specific action keyboard
        if task.duration_seconds > SUMMARIZE_THRESHOLD:
            tg_action_keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 Создать конспект", callback_data=f"summarize:{task.id}")
            ]])
            max_action_keyboard = _make_max_summarize_keyboard(task.id) if task.user_platform == PLATFORM_MAX else None
        else:
            tg_action_keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("📄 Отправить текстом", callback_data=f"send_as_text:{task.id}")
            ]])
            max_action_keyboard = _make_max_send_as_text_keyboard(task.id) if task.user_platform == PLATFORM_MAX else None

        done_text = (
            f"✅ Распознавание завершено\n\n"
            f"Длительность: {audio_duration_str}\n"
            f"Стоимость: {task.price_for_user} ₽\n\n"
            f"Время обработки: {duration_str}\n\n"
        )
        if sender is not None:
            await sender.edit_message(
                task.user_platform, task.user_id, task.message_id, done_text,
                tg_markup=tg_action_keyboard,
                max_keyboard=max_action_keyboard,
            )
        else:
            await safe_edit_message_text(
                context.bot, task.user_id, task.message_id, done_text,
                reply_markup=tg_action_keyboard,
            )

        try:
            tg_rating_keyboard = make_rating_keyboard(task.id)
            max_rating_keyboard = _make_max_rating_keyboard(task.id) if task.user_platform == PLATFORM_MAX else None

            with path.open("rb") as f:
                if sender is not None:
                    await sender.send_document(
                        task.user_platform,
                        task.user_id,
                        task.message_id,
                        f,
                        path.name,
                        RATING_PROMPT,
                        tg_markup=tg_rating_keyboard,
                        max_keyboard=max_rating_keyboard,
                        connect_timeout=15,
                        write_timeout=30,
                    )
                else:
                    await context.bot.send_document(
                        chat_id=task.user_id,
                        reply_to_message_id=int(task.message_id),
                        document=f,
                        caption=RATING_PROMPT,
                        reply_markup=tg_rating_keyboard,
                        connect_timeout=15,
                        write_timeout=30,
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
            "❌ Задача завершилась с ошибкой\n\n"
            "Попробуйте ещё раз"
        )
            if sender is not None:
                await sender.edit_message(task.user_platform, task.user_id, task.message_id, fail_text)
            else:
                await safe_edit_message_text(context.bot, task.user_id, task.message_id, fail_text)
        finally:
            path.unlink(missing_ok=True)
            tmp_dir.rmdir()
