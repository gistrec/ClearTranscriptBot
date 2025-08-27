import os
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from database.queries import add_transcription, add_user, get_user_by_telegram_id

from utils.ffmpeg import convert_to_ogg, get_media_duration
from utils.s3 import upload_file
from utils.sentry import sentry_bind_user
from utils.speechkit import cost_yc_async_rub, format_duration
from utils.tg import extract_local_path

USE_LOCAL_PTB = os.environ.get("USE_LOCAL_PTB") is not None


def _is_supported(mime: str) -> bool:
    return mime.startswith("audio/") or mime.startswith("video/")


@sentry_bind_user
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming media files."""
    message = update.message
    telegram_id = message.from_user.id
    user = get_user_by_telegram_id(telegram_id)
    if user is None:
        user = add_user(telegram_id, message.from_user.username)

    await message.reply_text(
        "Файл получен.\n\n"
        "Определяю длительность и стоимость перевода в текст. "
        "Скоро попрошу подтвердить запуск.",
    )

    file = None
    mime = ""
    file_name = "file"
    if message.document:
        file = await message.document.get_file(read_timeout=120)
        mime = message.document.mime_type or ""
        file_name = message.document.file_name or file_name
    elif message.audio:
        file = await message.audio.get_file()
        mime = message.audio.mime_type or ""
        file_name = message.audio.file_name or file_name
    elif message.video:
        file = await message.video.get_file(read_timeout=120)
        mime = message.video.mime_type or ""
        file_name = message.video.file_name or file_name
    elif message.voice:
        file = await message.voice.get_file(read_timeout=120)
        mime = "audio/ogg"
        file_name = "voice.ogg"
    else:
        await message.reply_text("Файл не поддерживается")
        return

    if not _is_supported(mime):
        await message.reply_text("Файл должен быть видео или аудио")
        return

    with tempfile.TemporaryDirectory() as workdir:
        workdir = Path(workdir)
        in_dir = workdir / "in"
        out_dir = workdir / "out"
        in_dir.mkdir()
        out_dir.mkdir()

        local_path = in_dir / Path(file_name).name

        if USE_LOCAL_PTB:
            file_path = extract_local_path(file.file_path)
            shutil.copy(file_path, local_path)  # читаем напрямую
        else:
            await file.download_to_drive(custom_path=str(local_path))

        duration = await get_media_duration(local_path)
        if not duration:
            await message.reply_text("Не удалось определить длительность файла")
            return
        price = cost_yc_async_rub(duration)
        price_dec = Decimal(price)
        if user.balance < price_dec:
            await message.reply_text(
                f"Недостаточно средств. Баланс: {user.balance} ₽, требуется: {price} ₽"
            )
            return

        ogg_name = f"{local_path.stem}.ogg"
        ogg_path = out_dir / ogg_name
        converted = await convert_to_ogg(local_path, ogg_path)
        if converted is None:
            await message.reply_text("Не удалось преобразовать файл")
            return

        object_name = f"source/{telegram_id}/{ogg_path.name}"
        s3_uri = await upload_file(ogg_path, object_name)
        if s3_uri is None:
            await message.reply_text("Не удалось загрузить файл. Попробуйте ещё раз")
            return

    history = add_transcription(
        telegram_id=telegram_id,
        status="pending",
        audio_s3_path=s3_uri,
        duration_seconds=int(duration),
        price_rub=price_dec,
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

    duration_str = format_duration(int(duration))
    await message.reply_text(
        f"Длительность: {duration_str}\nСтоимость: {price} ₽",
        reply_markup=InlineKeyboardMarkup([buttons]),
    )
