"""Handler for file/audio/video messages on Max messenger."""
import logging
import mimetypes
import tempfile

import aiomax

from pathlib import Path

from database.models import PLATFORM_MAX
from database.queries import add_transcription, add_user, get_user

import providers.speechkit as speechkit_provider

from utils.ffmpeg import convert_to_ogg, get_media_duration
from utils.max_download import download_max_file
from utils.s3 import upload_file
from utils.tg import is_supported_mime, sanitize_filename
from utils.utils import format_duration
from utils.sentry import sentry_bind_user_max


MAX_AUDIO_DURATION = 6 * 60 * 60  # seconds
LONG_AUDIO_THRESHOLD = 120  # seconds


@sentry_bind_user_max
async def handle_max_file(message: aiomax.Message, bot: aiomax.Bot) -> None:
    """Handle incoming file/audio/video attachments from Max."""
    try:
        user_id = int(message.sender.user_id)
    except (ValueError, TypeError):
        logging.error("Max: cannot parse user_id: %s", message.sender)
        return

    chat_id = message.recipient.chat_id

    user = get_user(user_id, PLATFORM_MAX)
    if user is None:
        user = add_user(user_id, PLATFORM_MAX)

    # Find the first supported attachment (also look inside forwarded message)
    attachment = None
    file_name = "file"
    mime = ""
    _linked = getattr(message.link, "message", None)
    _candidates = list(message.body.attachments or []) + list(getattr(_linked, "attachments", None) or [])
    for att in _candidates:
        att_type = type(att).__name__
        if att_type in ("FileAttachment", "AudioAttachment", "VideoAttachment"):
            attachment = att
            if hasattr(att, "filename") and att.filename:
                file_name = att.filename
                guessed, _ = mimetypes.guess_type(file_name)
                mime = guessed or ""
            elif att_type == "AudioAttachment":
                mime = "audio/ogg"
                file_name = "voice.ogg"
            elif att_type == "VideoAttachment":
                mime = "video/mp4"
                file_name = "video.mp4"
            break

    if attachment is None:
        return  # no supported attachment, ignore

    await bot.send_message(
        "📥 Файл получен\n\n"
        "Подготавливаю аудио и считаю стоимость\n"
        "Это может занять до 1 минуты",
        chat_id=chat_id,
    )

    file_url = getattr(attachment, "url", None)
    if not file_url:
        await bot.send_message("❌ Не удалось получить файл от Max", chat_id=chat_id)
        return

    file_bytes = await download_max_file(file_url)
    if not file_bytes:
        await bot.send_message(
            "❌ Не удалось загрузить файл\n"
            "Пожалуйста, попробуйте ещё раз",
            chat_id=chat_id,
        )
        return

    if mime and not is_supported_mime(mime):
        await bot.send_message(
            "❌ Этот тип файла не поддерживается\n"
            "Пожалуйста, отправьте видео или аудио",
            chat_id=chat_id,
        )
        return

    with tempfile.TemporaryDirectory() as workdir:
        workdir = Path(workdir)
        in_dir = workdir / "in"
        out_dir = workdir / "out"
        in_dir.mkdir()
        out_dir.mkdir()

        local_path = in_dir / file_name
        local_path.write_bytes(file_bytes)

        duration = await get_media_duration(local_path)
        if not duration:
            await bot.send_message(
                "❌ Не удалось определить длительность файла\n"
                "Возможно, формат не поддерживается или файл повреждён",
                chat_id=chat_id,
            )
            return

        duration_str = format_duration(int(duration))
        if duration > MAX_AUDIO_DURATION:
            max_duration_str = format_duration(MAX_AUDIO_DURATION)
            await bot.send_message(
                f"❌ Файл слишком длинный: {duration_str}\n"
                f"Максимально допустимая длительность — {max_duration_str}",
                chat_id=chat_id,
            )
            return

        price_for_user = speechkit_provider.cost_in_rub(duration)
        if user.balance < price_for_user:
            await bot.send_message(
                f"❌ Недостаточно средств\n"
                f"Баланс: {user.balance} ₽, требуется: {price_for_user} ₽\n\n"
                f"Для пополнения баланса используйте команду /topup",
                chat_id=chat_id,
            )
            return

        safe_stem = sanitize_filename(Path(file_name).stem)
        ogg_name = f"{safe_stem}.ogg"
        ogg_path = out_dir / ogg_name
        progress_path = out_dir / f"{safe_stem}.progress"

        convert_error = await convert_to_ogg(local_path, ogg_path, progress_path)
        if convert_error == "no_audio_stream":
            await bot.send_message(
                "❌ В этом файле не обнаружено аудио\n"
                "Пожалуйста, отправьте файл со звуком",
                chat_id=chat_id,
            )
            return
        elif convert_error:
            await bot.send_message(
                "❌ Не удалось обработать файл\n"
                "Возможно, он имеет неподдерживаемый формат",
                chat_id=chat_id,
            )
            return

        try:
            if local_path.exists():
                local_path.unlink()
        except Exception:
            logging.exception("Could not remove original file %s", local_path)

        object_name = f"source/{user_id}/{message.body.message_id}_{ogg_path.name}"
        s3_url, s3_signed_url = await upload_file(ogg_path, object_name)
        if not s3_url or not s3_signed_url:
            await bot.send_message(
                "❌ Не удалось загрузить файл\n"
                "Пожалуйста, попробуйте ещё раз чуть позже",
                chat_id=chat_id,
            )
            return

    provider = "replicate" if duration > LONG_AUDIO_THRESHOLD else "speechkit"

    history = add_transcription(
        user_id=user_id,
        platform=PLATFORM_MAX,
        status="pending",
        audio_s3_path=s3_url,
        provider=provider,
        duration_seconds=int(duration),
        price_for_user=price_for_user,
        result_s3_path=None,
    )

    from handlers.max.common import make_confirm_keyboard
    keyboard = make_confirm_keyboard(history.id)

    hint = "\n\n💡 Бот лучше всего работает с записями от 5 минут" if duration < 300 else ""
    confirm_msg = await bot.send_message(
        "🎧 Аудио подготовлено\n\n"
        f"Длительность: {duration_str}\n"
        f"Стоимость: {price_for_user} ₽"
        f"{hint}",
        chat_id=chat_id,
        keyboard=keyboard,
    )

    from database.queries import update_transcription
    update_transcription(history.id, message_id=str(confirm_msg.body.message_id))
