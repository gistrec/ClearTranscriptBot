"""Periodic scheduler for checking transcription statuses."""
import os
import pytz
import logging
import sentry_sdk

from pathlib import Path
from datetime import datetime, timedelta

from telegram.ext import ContextTypes

from database.queries import get_transcriptions_by_status, update_transcription
from utils.speechkit import fetch_transcription_result, parse_text, format_duration
from utils.tg import safe_edit_message_text
from utils.s3 import upload_file


EDIT_INTERVAL_SEC = 5  # не редактировать чаще, чем раз в 5 сек


MoscowTimezone = pytz.timezone('Europe/Moscow')


def _need_edit(context, task_id: int, now: datetime) -> bool:
    """Возвращает True, если прошло достаточно времени."""
    cache = context.bot_data.setdefault("status_cache", {})
    last_ts = cache.get(task_id)

    if not last_ts:
        # нет кэша, значит нужно редактировать
        cache[task_id] = now
        return True

    if now - last_ts < timedelta(seconds=EDIT_INTERVAL_SEC):
        return False

    cache[task_id] = now
    return True


async def check_running_tasks(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Poll running transcriptions and send results when ready."""
    now = datetime.now(MoscowTimezone)

    for task in get_transcriptions_by_status("running"):
        if not task.operation_id:
            logging.error(f"Task {task.id} doesn't have operation_id")
            continue

        if not task.started_at:
            logging.error(f"Task {task.id} doesn't have started_at")
            continue

        started_at = MoscowTimezone.localize(task.started_at)

        duration = int((now - started_at).total_seconds())
        duration_str = format_duration(duration)

        # Редактируем сообщение только если прошло достаточно времени
        if _need_edit(context, task.id, now):
            await safe_edit_message_text(
                context.bot,
                task.chat_id,
                task.message_id,
                f"🧠 Задача №{task.id} в работе\n\n"
                f"Прошло времени: {duration_str}\n\n"
                "Отправлю результат, как только всё будет готово",
            )

        result = await fetch_transcription_result(task.operation_id)

        # Результата еще нет, проверим снова через секунду
        if result is None:
            continue

        update_transcription(
            task.id,
            result_json=result,
            finished_at=now,
        )

        if "response" not in result:
            update_transcription(task.id, status="failed")
            await safe_edit_message_text(
                context.bot,
                task.chat_id,
                task.message_id,
                f"❌ Задача №{task.id} завершилась с ошибкой\n\nПопробуйте ещё раз",
            )
            continue

        text = parse_text(result)
        if not text.strip():
            text = "(речь в записи отсутствует или слишком неразборчива для распознавания)"

        source_stem = Path(task.audio_s3_path).stem
        path = Path(f"{source_stem}.txt")
        path.write_text(text, encoding="utf-8")

        object_name = f"result/{task.telegram_id}/{path.name}"
        s3_uri = await upload_file(path, object_name)
        if s3_uri is None:
            update_transcription(task.id, status="failed")
            await safe_edit_message_text(
                context.bot,
                task.chat_id,
                task.message_id,
                f"❌ Задача №{task.id} завершилась с ошибкой\n\nПопробуйте ещё раз",
            )
            path.unlink(missing_ok=True)
            continue

        await safe_edit_message_text(
            context.bot,
            task.chat_id,
            task.message_id,
            f"✅ Задача №{task.id} готова!\n\n"
            f"Прошло времени: {duration_str}\n\n"
            "Отправляю результат…",
        )

        try:
            await context.bot.send_document(chat_id=task.telegram_id, document=path.open("rb"))
            update_transcription(task.id, status="completed", result_s3_path=s3_uri)
        except Exception as e:
            logging.error(f"Failed to send result for task {task.id}: {e}")
            if os.getenv("ENABLE_SENTRY") == "1":
                sentry_sdk.capture_exception(e)

            update_transcription(task.id, status="failed", result_s3_path=s3_uri)

            await safe_edit_message_text(
                context.bot,
                task.chat_id,
                task.message_id,
                f"❌ Задача №{task.id} завершилась с ошибкой\n\nПопробуйте ещё раз",
            )
        finally:
            path.unlink(missing_ok=True)
