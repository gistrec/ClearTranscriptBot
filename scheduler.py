"""Periodic scheduler for checking transcription statuses."""
import time

from pathlib import Path
from datetime import datetime

from telegram.ext import ContextTypes

from database.queries import get_transcriptions_by_status, update_transcription
from utils.speechkit import fetch_transcription_result, parse_text, format_duration
from utils.s3 import upload_file


EDIT_INTERVAL_SEC = 5  # не редактировать чаще, чем раз в 5 сек


def _need_edit(context, task_id: int, text: str) -> bool:
    """Возвращает True, если прошло достаточно времени и текст реально изменился."""
    cache = context.bot_data.setdefault("status_cache", {})
    last_ts = cache.get(task_id)

    if not last_ts:
        # нет кэша, значит нужно редактировать
        cache[task_id] = time.monotonic()
        return False

    now = time.monotonic()
    if now - last_ts < EDIT_INTERVAL_SEC:
        return False

    cache[task_id] = now
    return True


async def safe_edit_message_text(bot, chat_id, message_id, text):
    """Safely edit a message text, catching exceptions."""
    if not chat_id or not message_id:
        return
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
    except Exception as e:
        print(f"Failed to edit message {message_id} in chat {chat_id}: {e}")


async def check_running_tasks(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Poll running transcriptions and send results when ready."""
    bot = context.bot
    now = datetime.utcnow()
    tasks = get_transcriptions_by_status("running")
    for task in tasks:
        if not task.operation_id:
            print(f"Task {task.id} doesn't have operation_id")
            continue

        duration = int((now - task.created_at).total_seconds())
        duration_str = format_duration(duration)

        # Редактируем сообщение только если прошло достаточно времени
        if _need_edit(context, task.id, duration_str):
            await safe_edit_message_text(
                bot,
                task.chat_id,
                task.message_id,
                f"🧠 Задача №{task.id} в работе.\n\n"
                f"Прошло времени: {duration_str}\n\n"
                "Отправлю результат, как только всё будет готово.",
            )

        result = fetch_transcription_result(task.operation_id)

        # Результата еще нет, проверим снова через секунду
        if result is None:
            continue

        update_transcription(task.id, result_json=result)

        if "response" not in result:
            update_transcription(task.id, status="failed")
            await safe_edit_message_text(
                bot,
                task.chat_id,
                task.message_id,
                f"❌ Задача №{task.id} завершилась с ошибкой. Попробуйте ещё раз.",
            )
            continue

        text = parse_text(result)

        source_stem = Path(task.audio_s3_path).stem
        path = Path(f"{source_stem}.txt")
        path.write_text(text, encoding="utf-8")

        object_name = f"result/{task.telegram_id}/{path.name}"
        s3_uri = upload_file(path, object_name)

        await safe_edit_message_text(
            bot,
            task.chat_id,
            task.message_id,
            f"✅ Задача №{task.id} готова!\n\n"
            f"Прошло времени: {duration_str}\n\n"
            "Отправляю результат…",
        )

        try:
            await bot.send_document(chat_id=task.telegram_id, document=path.open("rb"))
            update_transcription(task.id, status="completed", result_s3_path=s3_uri)
        except Exception:
            print("Ошибка во время отправки результата")
            update_transcription(task.id, status="failed", result_s3_path=s3_uri)
            await safe_edit_message_text(
                bot,
                task.chat_id,
                task.message_id,
                f"❌ Задача №{task.id} завершилась с ошибкой. Попробуйте ещё раз.",
            )
        finally:
            path.unlink(missing_ok=True)
