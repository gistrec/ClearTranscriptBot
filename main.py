"""Telegram bot for ClearTranscriptBot."""
import os
import tempfile
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from database.queries import (
    add_transcription,
    add_user,
    get_user_by_telegram_id,
    get_transcription,
    update_transcription,
)
from utils.ffmpeg import convert_to_ogg, get_media_duration
from utils.s3 import upload_file
from utils.speechkit import run_transcription, cost_yc_async_rub
from scheduler import check_running_tasks

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN must be set")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond to regular text messages."""
    await update.message.reply_text(
        "Отправьте видео или аудио, чтобы получить его трансрибацию"
    )


def _is_supported(mime: str) -> bool:
    return mime.startswith("audio/") or mime.startswith("video/")


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming media files."""
    message = update.message
    telegram_id = message.from_user.id
    if get_user_by_telegram_id(telegram_id) is None:
        add_user(telegram_id, message.from_user.username)

    file = None
    mime = ""
    file_name = "file"
    if message.document:
        file = await message.document.get_file()
        mime = message.document.mime_type or ""
        file_name = message.document.file_name or file_name
    elif message.audio:
        file = await message.audio.get_file()
        mime = message.audio.mime_type or ""
        file_name = message.audio.file_name or file_name
    elif message.video:
        file = await message.video.get_file()
        mime = message.video.mime_type or ""
        file_name = message.video.file_name or file_name
    elif message.voice:
        file = await message.voice.get_file()
        mime = "audio/ogg"
        file_name = "voice.ogg"
    else:
        await message.reply_text("Файл не поддерживается")
        return

    if not _is_supported(mime):
        await message.reply_text("Файл должен быть видео или аудио")
        return

    await message.reply_text(
        "Файл получен.\n"
        "Начинаю анализ длительности и стоимости транскрибации. "
        "Скоро потребуется подтверждение для запуска задачи.",
    )

    with tempfile.TemporaryDirectory() as workdir:
        workdir = Path(workdir)
        in_dir = workdir / "in"
        out_dir = workdir / "out"
        in_dir.mkdir()
        out_dir.mkdir()

        local_path = in_dir / Path(file_name).name
        await file.download_to_drive(custom_path=str(local_path))

        duration = get_media_duration(local_path)
        price = cost_yc_async_rub(duration)

        ogg_name = f"{local_path.stem}.ogg"
        ogg_path = out_dir / ogg_name
        convert_to_ogg(local_path, ogg_path)

        object_name = f"source/{telegram_id}/{ogg_path.name}"
        s3_uri = upload_file(ogg_path, object_name)

    history = add_transcription(
        telegram_id=telegram_id,
        status="pending",
        audio_s3_path=s3_uri,
        duration_seconds=int(duration),
        result_s3_path=None,
    )

    buttons = [
        InlineKeyboardButton(
            "Распознать", callback_data=f"create_task:{history.id}"
        ),
        InlineKeyboardButton(
            "Отменить", callback_data=f"cancel_task:{history.id}"
        ),
    ]
    await message.reply_text(
        f"Длительность: {duration:.1f} сек\nСтоимость: {price} ₽",
        reply_markup=InlineKeyboardMarkup([buttons]),
    )


async def handle_create_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    try:
        _, id_str = data.split(":", 1)
        task_id = int(id_str)
    except ValueError:
        await query.edit_message_text("Некорректная задача")
        return

    task = get_transcription(task_id)
    telegram_id = query.from_user.id
    if task is None or task.telegram_id != telegram_id:
        await query.edit_message_text("Задача не найдена")
        return
    if task.status != "pending":
        await query.edit_message_text("Задача уже запущена")
        return

    operation_id = run_transcription(task.audio_s3_path)
    update_transcription(task.id, status="running", operation_id=operation_id)

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("Задача создана, начинаю распознавание")


async def handle_cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    try:
        _, id_str = data.split(":", 1)
        task_id = int(id_str)
    except ValueError:
        await query.edit_message_text("Некорректная задача")
        return

    task = get_transcription(task_id)
    telegram_id = query.from_user.id
    if task is None or task.telegram_id != telegram_id:
        await query.edit_message_text("Задача не найдена")
        return
    if task.status != "pending":
        await query.edit_message_text("Задача уже обработана")
        return

    update_transcription(task.id, status="cancelled")

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("Задача отменена")


def main() -> None:
    """Start the Telegram bot."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(MessageHandler(filters.TEXT, handle_text))
    file_filters = filters.Document.ALL | filters.AUDIO | filters.VIDEO | filters.VOICE
    application.add_handler(MessageHandler(file_filters, handle_file))
    application.add_handler(
        CallbackQueryHandler(handle_create_task, pattern=r"^create_task:\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_cancel_task, pattern=r"^cancel_task:\\d+$")
    )
    application.job_queue.run_repeating(check_running_tasks, interval=1.0)
    application.run_polling()


if __name__ == "__main__":
    main()
