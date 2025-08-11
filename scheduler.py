"""Periodic scheduler for checking transcription statuses."""
from pathlib import Path
from datetime import datetime

from telegram.ext import ContextTypes

from database.queries import get_transcriptions_by_status, update_transcription
from utils.speechkit import fetch_transcription_result, parse_text, format_duration
from utils.s3 import upload_file


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
        if (
            duration > 0
            and duration % 5 == 0
            and task.chat_id
            and task.message_id
        ):
            try:
                await bot.edit_message_text(
                    chat_id=task.chat_id,
                    message_id=task.message_id,
                    text=(
                        f"🧠 Задача №{task.id} в работе\n\n"
                        f"Прошло времени: {format_duration(duration)}\n\n"
                        "Отправлю результат, как только всё будет готово."
                    ),
                )
            except Exception:
                pass

        result = fetch_transcription_result(task.operation_id)

        # Результата еще нет
        if result is None:
            continue

        update_transcription(task.id, result_json=result)

        if "response" not in result:
            update_transcription(task.id, status="failed")
            if task.chat_id and task.message_id:
                try:
                    await bot.edit_message_text(
                        chat_id=task.chat_id,
                        message_id=task.message_id,
                        text=(
                            f"❌ Задача №{task.id} завершилась с ошибкой. Попробуйте ещё раз."
                        ),
                    )
                except Exception:
                    pass
            continue

        text = parse_text(result)

        source_stem = Path(task.audio_s3_path).stem
        path = Path(f"{source_stem}.txt")
        path.write_text(text, encoding="utf-8")

        object_name = f"result/{task.telegram_id}/{path.name}"
        s3_uri = upload_file(path, object_name)

        duration = int((datetime.utcnow() - task.created_at).total_seconds())
        duration_text = format_duration(duration)
        if task.chat_id and task.message_id:
            try:
                await bot.edit_message_text(
                    chat_id=task.chat_id,
                    message_id=task.message_id,
                    text=(
                        f"✅ Задача №{task.id} готова!\n\n"
                        f"Прошло времени: {duration_text}\n\n"
                        "Отправляю результат…"
                    ),
                )
            except Exception:
                pass

        try:
            await bot.send_document(chat_id=task.telegram_id, document=path.open("rb"))
            update_transcription(task.id, status="completed", result_s3_path=s3_uri)
        except Exception:
            print("Ошибка во время отправки результата")
            update_transcription(task.id, status="failed", result_s3_path=s3_uri)
            if task.chat_id and task.message_id:
                try:
                    await bot.edit_message_text(
                        chat_id=task.chat_id,
                        message_id=task.message_id,
                        text=(
                            f"❌ Задача №{task.id} завершилась с ошибкой. Попробуйте ещё раз."
                        ),
                    )
                except Exception:
                    pass
        finally:
            path.unlink(missing_ok=True)
