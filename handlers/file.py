import os
import logging
import tempfile

import providers.speechkit as speechkit_provider

from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM
from database.queries import add_transcription, add_user, get_user

from utils.ffmpeg import convert_to_ogg, get_media_duration
from utils.s3 import upload_file
from utils.sentry import sentry_bind_user
from utils.tg import is_supported_mime, sanitize_filename, extract_local_path
from utils.utils import format_duration


USE_LOCAL_PTB = os.environ.get("USE_LOCAL_PTB") is not None

MAX_AUDIO_DURATION = 6 * 60 * 60  # seconds; files longer than this are rejected outright
LONG_AUDIO_THRESHOLD = 120  # seconds; files longer than this use Replicate


@sentry_bind_user
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming media files."""
    message = update.message
    user_id = message.from_user.id
    user = get_user(user_id, PLATFORM_TELEGRAM)
    if user is None:
        user = add_user(user_id, PLATFORM_TELEGRAM)

    await message.reply_text(
        "📥 Файл получен\n\n"
        "Подготавливаю аудио и считаю стоимость\n"
        "Это может занять до 1 минуты",
    )

    try:
        file = None
        mime = ""
        file_name = "file"
        if message.document:
            file = await message.document.get_file(read_timeout=120)
            mime = message.document.mime_type or ""
            file_name = message.document.file_name or file_name
        elif message.audio:
            file = await message.audio.get_file(read_timeout=120)
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
            await message.reply_text(
                "❌ Этот тип файла не поддерживается\n"
                "Пожалуйста, отправьте видео или аудио"
            )
            return
    except Exception:
        logging.exception("Failed to get file from Telegram")
        await message.reply_text(
            "❌ Не удалось загрузить файл от Telegram\n"
            "Пожалуйста, попробуйте ещё раз"
        )
        return

    if not is_supported_mime(mime):
        await message.reply_text(
            "❌ Этот тип файла не поддерживается\n"
            "Пожалуйста, отправьте видео или аудио"
        )
        return

    with tempfile.TemporaryDirectory() as workdir:
        workdir = Path(workdir)
        in_dir = workdir / "in"
        out_dir = workdir / "out"
        in_dir.mkdir()
        out_dir.mkdir()

        local_path = in_dir / Path(file_name).name

        try:
            if USE_LOCAL_PTB:
                file_path = extract_local_path(file.file_path)
                local_path.symlink_to(file_path)
            else:
                await file.download_to_drive(custom_path=str(local_path))
        except Exception:
            logging.exception("Failed to download file to disk")
            await message.reply_text(
                "❌ Не удалось скачать файл\n"
                "Пожалуйста, попробуйте ещё раз"
            )
            return

        duration = await get_media_duration(local_path)
        if not duration:
            await message.reply_text(
                "❌ Не удалось определить длительность файла\n"
                "Возможно, формат не поддерживается или файл повреждён"
            )
            return

        duration_str = format_duration(int(duration))
        if duration > MAX_AUDIO_DURATION:
            max_duration_str = format_duration(MAX_AUDIO_DURATION)
            await message.reply_text(
                f"❌ Файл слишком длинный: {duration_str}\n"
                f"Максимально допустимая длительность — {max_duration_str}"
            )
            return

        price_for_user = speechkit_provider.cost_in_rub(duration)
        if user.balance < price_for_user:
            await message.reply_text(
                f"❌ Недостаточно средств\n"
                f"Баланс: {user.balance} ₽, требуется: {price_for_user} ₽\n\n"
                f"Для пополнения баланса используйте команду /topup"
            )
            return

        safe_stem = sanitize_filename(local_path.stem)

        ogg_name = f"{safe_stem}.ogg"
        ogg_path = out_dir / ogg_name

        progress_name = f"{safe_stem}.progress"
        progress_path = out_dir / progress_name

        convert_error = await convert_to_ogg(local_path, ogg_path, progress_path)
        if convert_error == "no_audio_stream":
            await message.reply_text(
                "❌ В этом файле не обнаружено аудио\n"
                "Пожалуйста, отправьте файл со звуком"
            )
            return
        elif convert_error:
            await message.reply_text(
                "❌ Не удалось обработать файл\n"
                "Возможно, он имеет неподдерживаемый формат"
            )
            return

        object_name = f"source/{user_id}/{message.message_id}_{ogg_path.name}"
        s3_url, s3_signed_url = await upload_file(ogg_path, object_name)
        if not s3_url or not s3_signed_url:
            await message.reply_text(
                "❌ Не удалось загрузить файл\n"
                "Пожалуйста, попробуйте ещё раз чуть позже"
            )
            return

    provider = "replicate" if duration > LONG_AUDIO_THRESHOLD else "speechkit"

    history = add_transcription(
        user_id=user_id,
        platform=PLATFORM_TELEGRAM,
        status="pending",
        audio_s3_path=s3_url,
        provider=provider,
        duration_seconds=int(duration),
        price_for_user=price_for_user,
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
        "🎧 Аудио подготовлено\n\n"
        f"Длительность: {duration_str}\n"
        f"Стоимость: {price_for_user} ₽",
        reply_markup=InlineKeyboardMarkup([buttons]),
    )
