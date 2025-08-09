"""Periodic scheduler for checking transcription statuses."""
from pathlib import Path

from telegram.ext import ContextTypes

from database.queries import get_transcriptions_by_status, update_transcription
from utils.speechkit import fetch_transcription_result, parse_text
from utils.s3 import upload_file


async def check_running_tasks(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Poll running transcriptions and send results when ready."""
    bot = context.bot
    tasks = get_transcriptions_by_status("running")
    for task in tasks:
        if not task.operation_id:
            print(f"Task {task.id} doesn't have operation_id")
            continue

        result = fetch_transcription_result(task.operation_id)

        # Результата еще нет
        if result is None:
            continue

        update_transcription(task.id, result_json=result)

        if "response" not in result:
            error = result.get("error", "Unknown error")
            update_transcription(task.id, status="failed")
            continue

        text = parse_text(result)

        source_stem = Path(task.audio_s3_path).stem
        path = Path(f"{source_stem}.txt")
        path.write_text(text, encoding="utf-8")

        object_name = f"result/{task.telegram_id}/{path.name}"
        s3_uri = upload_file(path, object_name)

        try:
            await bot.send_document(chat_id=task.telegram_id, document=path.open("rb"))
            update_transcription(task.id, status="completed", result_s3_path=s3_uri)
        except Exception as e:
            print("Ошибка во время отправки результата")
            update_transcription(task.id, status="failed", result_s3_path=s3_uri)
        finally:
            path.unlink(missing_ok=True)
