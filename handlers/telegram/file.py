import asyncio
import math
import os
import logging
import tempfile
import time

import providers.speechkit as speechkit_provider

from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM, PROVIDER_REPLICATE, STATUS_PENDING
from database.queries import add_transcription, add_user, get_user

from utils.ffmpeg import convert_to_ogg, get_conversion_progress, get_media_duration
from utils.s3 import upload_file
from utils.sentry import sentry_bind_user, sentry_transaction
from utils.tg import ANCHOR, is_supported_mime, sanitize_filename, truncate_filename, extract_local_path
from utils.utils import format_duration, MAX_AUDIO_DURATION, MIN_PRICE_RUB
from messengers.telegram import make_topup_amounts_keyboard, safe_delete_message, safe_edit_message, safe_reply_text


USE_LOCAL_PTB = os.environ.get("USE_LOCAL_PTB") is not None

# Files below this prepare in seconds — staged progress would only flicker.
PROGRESS_THRESHOLD_BYTES = 20 * 1024 * 1024
TICKER_INTERVAL = 2.0  # seconds between progress edits, safely under edit rate limits


def _get_file_timeout(size_bytes):
    # In local Bot API mode getFile blocks for the whole server-side download, so
    # a flat timeout either fails big files or makes small ones hang on a stall.
    # Budget ~10 MB/s: small files fail fast, only large ones wait, capped ~10 min.
    if not size_bytes:
        return 120
    return int(min(600, 60 + (size_bytes / 1_000_000) / 10))


def format_size(size_bytes: int) -> str:
    mb = size_bytes / (1024 * 1024)
    if mb < 1024:
        return f"{mb:.0f} МБ"
    return f"{mb / 1024:.1f} ГБ"


def download_estimate_minutes(size_bytes: int) -> int:
    # Same ~10 MB/s budget as _get_file_timeout.
    return max(1, math.ceil(size_bytes / 1_000_000 / 10 / 60))


async def _download_ticker(bot, chat_id, message_id, watch_root: Path, baseline: set, expected_size: int) -> None:
    """Poll the bot-api working dir and report download progress.

    getFile gives no progress signal, so this watches for a new file growing
    under the local bot-api directory and assumes it is ours. If several new
    files grow at once (parallel downloads), attribution is impossible — keep
    the static text rather than risk showing someone else's progress.
    """
    started = time.time()
    sizes = {}
    matched = None
    last_text = None
    while True:
        await asyncio.sleep(TICKER_INTERVAL)
        if matched is None:
            try:
                fresh = {p for p in watch_root.glob("*/*") if p.is_file()} - baseline
            except OSError:
                continue
            growing = []
            for path in fresh:
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if size > sizes.get(path, -1):
                    growing.append(path)
                sizes[path] = size
            if len(growing) != 1:
                continue  # nothing new yet, or several candidates — cannot attribute
            matched = growing[0]
            logging.info("Download progress: tracking %s", matched.name)
        try:
            size = matched.stat().st_size
        except OSError:
            return  # the file moved away — bot-api is finalizing the download
        percent = min(99, int(size * 100 / expected_size))
        if percent <= 0:
            continue
        eta = max(0.0, (expected_size - size) / (size / (time.time() - started)))
        text = (
            f"📥 Скачиваю файл… {percent}%\n\n"
            f"Осталось примерно {format_duration(int(eta))}"
        )
        if text == last_text:
            continue  # progress has not visibly moved — do not burn the edit quota
        last_text = text
        await safe_edit_message(bot, chat_id, message_id, text)


async def _conversion_ticker(bot, chat_id, message_id, progress_path, duration: float) -> None:
    started = time.time()
    while True:
        await asyncio.sleep(TICKER_INTERVAL)
        percent, _, eta = await get_conversion_progress(progress_path, duration, started)
        if percent <= 0:
            continue  # ffmpeg has not reported anything yet, keep the stage text
        await safe_edit_message(
            bot, chat_id, message_id,
            f"🎬 Извлекаю аудиодорожку… {percent}%\n\n"
            f"Осталось примерно {format_duration(int(eta))}",
        )


@sentry_bind_user
@sentry_transaction(name="file.upload", op="telegram.message")
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming media files."""
    message = update.message
    if message is None:  # edited_message updates have no .message
        return
    user_id = message.from_user.id
    user = get_user(user_id, PLATFORM_TELEGRAM)
    if user is None:
        user = add_user(user_id, PLATFORM_TELEGRAM)

    incoming = message.document or message.audio or message.video or message.voice or message.video_note
    file_size = getattr(incoming, "file_size", None) or 0
    file_timeout = _get_file_timeout(file_size)
    show_progress = file_size > PROGRESS_THRESHOLD_BYTES

    if show_progress:
        ack_text = (
            f"📥 Файл получен ({format_size(file_size)})\n\n"
            f"Скачиваю файл — обычно это занимает до {download_estimate_minutes(file_size)} мин."
        )
    else:
        ack_text = (
            "📥 Файл получен\n\n"
            "Подготавливаю аудио и считаю стоимость\n"
            "Это может занять до 1 минуты"
        )
    ack = await safe_reply_text(message, ack_text)
    show_progress = show_progress and ack is not None

    download_ticker = None
    if show_progress and USE_LOCAL_PTB:
        watch_root = Path(ANCHOR) / context.bot.token
        try:
            baseline = {p for p in watch_root.glob("*/*") if p.is_file()}
            download_ticker = context.application.create_task(
                _download_ticker(context.bot, ack.chat_id, ack.message_id, watch_root, baseline, file_size)
            )
        except OSError:
            logging.exception("Could not snapshot bot-api dir for download progress")

    try:
        file = None
        mime = ""
        file_name = "file"
        if message.document:
            file = await message.document.get_file(read_timeout=file_timeout)
            mime = message.document.mime_type or ""
            file_name = message.document.file_name or file_name
        elif message.audio:
            file = await message.audio.get_file(read_timeout=file_timeout)
            mime = message.audio.mime_type or ""
            file_name = message.audio.file_name or file_name
        elif message.video:
            file = await message.video.get_file(read_timeout=file_timeout)
            mime = message.video.mime_type or ""
            file_name = message.video.file_name or file_name
        elif message.voice:
            file = await message.voice.get_file(read_timeout=file_timeout)
            mime = "audio/ogg"
            file_name = "voice.ogg"
        elif message.video_note:
            file = await message.video_note.get_file(read_timeout=file_timeout)
            mime = "video/mp4"
            file_name = "video_note.mp4"
        else:
            await safe_reply_text(
                message,
                "❌ Этот тип файла не поддерживается\n\n"
                "Пожалуйста, отправьте видео или аудио"
            )
            return
    except Exception:
        logging.exception("Failed to get file from Telegram")
        await safe_reply_text(
            message,
            "❌ Не удалось загрузить файл от Telegram\n\n"
            "Пожалуйста, попробуйте ещё раз"
        )
        return
    finally:
        # Await the cancellation so no in-flight ticker edit can land after
        # the next stage text.
        if download_ticker is not None:
            download_ticker.cancel()
            try:
                await download_ticker
            except asyncio.CancelledError:
                pass
            except Exception:
                logging.exception("Download progress ticker failed")

    if not is_supported_mime(mime):
        await safe_reply_text(
            message,
            "❌ Этот тип файла не поддерживается\n\n"
            "Пожалуйста, отправьте видео или аудио"
        )
        return

    with tempfile.TemporaryDirectory() as workdir:
        workdir = Path(workdir)
        in_dir = workdir / "in"
        out_dir = workdir / "out"
        in_dir.mkdir()
        out_dir.mkdir()

        local_path = in_dir / truncate_filename(Path(file_name).name)

        try:
            if USE_LOCAL_PTB:
                file_path = extract_local_path(file.file_path)
                local_path.symlink_to(file_path)
            else:
                await file.download_to_drive(custom_path=str(local_path))
        except Exception:
            logging.exception("Failed to download file to disk")
            await safe_reply_text(
                message,
                "❌ Не удалось скачать файл\n\n"
                "Пожалуйста, попробуйте ещё раз"
            )
            return

        duration = await get_media_duration(local_path)
        if not duration:
            await safe_reply_text(
                message,
                "❌ Не удалось определить длительность файла\n\n"
                "Возможно, формат не поддерживается или файл повреждён"
            )
            return

        duration_str = format_duration(int(duration))
        if duration > MAX_AUDIO_DURATION:
            max_duration_str = format_duration(MAX_AUDIO_DURATION)
            await safe_reply_text(
                message,
                f"❌ Файл слишком длинный: {duration_str}\n\n"
                f"Максимально допустимая длительность — {max_duration_str}"
            )
            return

        price_for_user = max(MIN_PRICE_RUB, speechkit_provider.cost_in_rub(duration))
        # Not enough balance is no longer a dead end: the task is still
        # prepared, and a topup prompt follows the confirm message below.
        needs_topup = user.balance < price_for_user

        safe_stem = sanitize_filename(local_path.stem)

        ogg_name = f"{safe_stem}.ogg"
        ogg_path = out_dir / ogg_name

        progress_name = f"{safe_stem}.progress"
        progress_path = out_dir / progress_name

        ticker = None
        if show_progress:
            await safe_edit_message(context.bot, ack.chat_id, ack.message_id, "🎬 Извлекаю аудиодорожку…")
            ticker = context.application.create_task(
                _conversion_ticker(context.bot, ack.chat_id, ack.message_id, progress_path, duration)
            )
        try:
            convert_error = await convert_to_ogg(local_path, ogg_path, progress_path)
        finally:
            # Await the cancellation so no in-flight ticker edit can land after
            # the next stage text (or after the tempdir is gone).
            if ticker is not None:
                ticker.cancel()
                try:
                    await ticker
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logging.exception("Conversion progress ticker failed")
        if convert_error:
            if convert_error == "no_audio_stream":
                error_text = (
                    "❌ В этом файле не обнаружено аудио\n\n"
                    "Пожалуйста, отправьте файл со звуком"
                )
            elif convert_error == "moov_atom_not_found":
                error_text = (
                    "❌ Файл повреждён — запись была прервана и не сохранена до конца\n\n"
                    "Попробуйте записать снова"
                )
            else:
                error_text = (
                    "❌ Не удалось обработать файл\n\n"
                    "Возможно, он имеет неподдерживаемый формат"
                )
            await safe_reply_text(message, error_text)
            await upload_file(local_path, f"error/{user_id}/{message.message_id}_{local_path.name}")
            return

        try:
            real_path = local_path.resolve()
            if real_path.exists():
                real_path.unlink()
        except Exception:
            logging.exception("Could not remove original file %s", local_path)

        if show_progress:
            await safe_edit_message(context.bot, ack.chat_id, ack.message_id, "✨ Почти готово…")

        object_name = f"source/{user_id}/{message.message_id}_{ogg_path.name}"
        s3_url = await upload_file(ogg_path, object_name)
        if not s3_url:
            await safe_reply_text(
                message,
                "❌ Не удалось загрузить файл\n\n"
                "Пожалуйста, попробуйте ещё раз чуть позже"
            )
            return

    history = add_transcription(
        user_id=user_id,
        platform=PLATFORM_TELEGRAM,
        status=STATUS_PENDING,
        audio_s3_path=s3_url,
        provider=PROVIDER_REPLICATE,
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

    hint = "\n\n💡 Бот лучше всего работает с записями от 5 минут" if duration < 300 else ""
    confirm = await safe_reply_text(
        message,
        "<b>🎧 Аудио подготовлено</b>\n\n"
        f"Длительность: {duration_str}\n"
        f"Стоимость: {price_for_user} ₽"
        f"{hint}",
        reply_markup=InlineKeyboardMarkup([buttons]),
        parse_mode="HTML",
    )

    if confirm is not None and ack is not None:
        # The confirm message carries all the info — the staged ack is now clutter.
        await safe_delete_message(context.bot, ack.chat_id, ack.message_id)

    if needs_topup:
        await safe_reply_text(
            message,
            f"⚠️ На балансе не хватает средств\n\n"
            f"Баланс: {user.balance} ₽, стоимость: {price_for_user} ₽\n\n"
            f"Пополните баланс и нажмите «Распознать»",
            reply_markup=make_topup_amounts_keyboard(),
        )
