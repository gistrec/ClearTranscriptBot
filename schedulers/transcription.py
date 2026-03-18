"""Periodic scheduler for checking transcription statuses."""
import logging
import tempfile

import providers.replicate as replicate_provider
import providers.speechkit as speechkit_provider

from pathlib import Path
from datetime import datetime, timedelta

from telegram.ext import ContextTypes

from database.queries import change_user_balance, get_transcriptions_by_status, update_transcription
from handlers.rate_transcription import make_rating_keyboard, RATING_PROMPT
from utils.utils import format_duration, MoscowTimezone

from utils.transcription import check_transcription, get_result
from utils.tg import safe_edit_message_text
from utils.s3 import upload_file
from utils.tokens import tokens_by_model


EDIT_INTERVAL_SEC = 5  # не редактировать чаще, чем раз в 5 сек


def _need_edit(context, task_id: int, now: datetime) -> bool:
    """Возвращает True, если прошло достаточно времени."""
    cache = context.bot_data.setdefault("status_cache", {})
    last_ts = cache.get(task_id)

    if not last_ts:
        # Если нет кэша, значит не нужно редактировать
        # Скорее всего новый текст будет таким же, как предыдущий
        cache[task_id] = now
        return False

    if now - last_ts < timedelta(seconds=EDIT_INTERVAL_SEC):
        return False

    cache[task_id] = now
    return True


async def check_running_tasks(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Poll running transcriptions and send results when ready."""
    now = datetime.now(MoscowTimezone)

    for task in get_transcriptions_by_status("running"):
        started_at = task.started_at.replace(tzinfo=MoscowTimezone)

        duration = int((now - started_at).total_seconds())
        duration_str = format_duration(duration)

        # Редактируем сообщение только если прошло достаточно времени
        if not task.shadow and _need_edit(context, task.id, now):
            audio_duration_str = format_duration(task.duration_seconds)
            await safe_edit_message_text(
                context.bot,
                task.telegram_id,
                task.message_id,
                f"⏳ Задача №{task.id} в работе\n\n"
                f"Длительность: {audio_duration_str}\n"
                f"Стоимость: {task.price_for_user} ₽\n\n"
                f"Время обработки: {duration_str}\n\n"
            )

        result_info = await check_transcription(task.operation_id, provider=task.provider)

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
            if not task.shadow:
                change_user_balance(task.telegram_id, task.price_for_user)  # Refund if failed
                await safe_edit_message_text(
                    context.bot,
                    task.telegram_id,
                    task.message_id,
                    f"❌ Задача №{task.id} завершилась с ошибкой\n\nПопробуйте ещё раз",
                )
            continue

        text = get_result(result_info)
        token_counts = tokens_by_model(text)

        if not text:
            text = "(речь в записи отсутствует или слишком неразборчива для распознавания)"

        source_stem = Path(task.audio_s3_path).stem
        tmp_dir = Path(tempfile.mkdtemp())
        file_stem = f"{source_stem}_shadow" if task.shadow else source_stem
        path = tmp_dir / f"{file_stem}.txt"
        path.write_text(text, encoding="utf-8")

        object_name = f"result/{task.telegram_id}/{path.name}"
        s3_url, s3_signed_url = await upload_file(path, object_name)
        if not s3_url or not s3_signed_url:
            update_transcription(task.id, status="failed")
            if not task.shadow:
                change_user_balance(task.telegram_id, task.price_for_user)  # Refund if upload failed
                await safe_edit_message_text(
                    context.bot,
                    task.telegram_id,
                    task.message_id,
                    f"❌ Задача №{task.id} завершилась с ошибкой\n\nПопробуйте ещё раз",
                )
            path.unlink(missing_ok=True)
            tmp_dir.rmdir()
            continue

        if not task.shadow:
            audio_duration_str = format_duration(task.duration_seconds)
            await safe_edit_message_text(
                context.bot,
                task.telegram_id,
                task.message_id,
                f"✅ Задача №{task.id} готова!\n\n"
                f"Длительность: {audio_duration_str}\n"
                f"Стоимость: {task.price_for_user} ₽\n\n"
                f"Время обработки: {duration_str}\n\n"
            )

        try:
            if not task.shadow:
                with path.open("rb") as f:
                    await context.bot.send_document(
                        chat_id=task.telegram_id,
                        reply_to_message_id=task.message_id,
                        document=f,
                        caption=RATING_PROMPT,
                        reply_markup=make_rating_keyboard(task.id),
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
            if not task.shadow:
                change_user_balance(task.telegram_id, task.price_for_user)  # Refund if sending failed
                await safe_edit_message_text(
                    context.bot,
                    task.telegram_id,
                    task.message_id,
                    f"❌ Задача №{task.id} завершилась с ошибкой\n\nПопробуйте ещё раз",
                )
        finally:
            path.unlink(missing_ok=True)
            tmp_dir.rmdir()
