"""Handler for file/audio/video messages on Max messenger."""
import asyncio
import logging
import math
import mimetypes
import tempfile
import time
import aiomax

from pathlib import Path

from database.models import PLATFORM_MAX, PROVIDER_REPLICATE, STATUS_PENDING
from database.queries import add_transcription, add_user, get_user, update_transcription

import providers.speechkit as speechkit_provider

from utils.ffmpeg import convert_to_ogg, get_conversion_progress, get_media_duration
from utils.max_download import download_max_file
from utils.s3 import upload_file
from utils.tg import is_supported_mime, sanitize_filename, truncate_filename
from utils.utils import format_duration, MAX_AUDIO_DURATION, MIN_PRICE_RUB
from utils.sentry import sentry_bind_user_max, sentry_transaction
from messengers.max import make_confirm_keyboard, make_topup_amounts_keyboard, safe_delete_message, safe_edit_message, safe_send_message


# Files below this prepare in seconds — staged progress would only flicker.
PROGRESS_THRESHOLD_BYTES = 20 * 1024 * 1024
TICKER_INTERVAL = 2.0  # seconds between progress edits, safely under edit rate limits


def format_size(size_bytes: int) -> str:
    mb = size_bytes / (1024 * 1024)
    if mb < 1024:
        return f"{mb:.0f} МБ"
    return f"{mb / 1024:.1f} ГБ"


def download_estimate_minutes(size_bytes: int) -> int:
    # Same ~10 MB/s budget as the Telegram handler uses.
    return max(1, math.ceil(size_bytes / 1_000_000 / 10 / 60))


async def _download_ticker(bot, message_id, local_path: Path, expected_size: int) -> None:
    started = time.time()
    last_text = None
    while True:
        await asyncio.sleep(TICKER_INTERVAL)
        try:
            size = local_path.stat().st_size
        except OSError:
            continue  # the download has not created the file yet
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
        await safe_edit_message(bot, message_id, text)


async def _conversion_ticker(bot, message_id, progress_path, duration: float) -> None:
    started = time.time()
    while True:
        await asyncio.sleep(TICKER_INTERVAL)
        percent, _, eta = await get_conversion_progress(progress_path, duration, started)
        if percent <= 0:
            continue  # ffmpeg has not reported anything yet, keep the stage text
        await safe_edit_message(
            bot, message_id,
            f"🎬 Извлекаю аудиодорожку… {percent}%\n\n"
            f"Осталось примерно {format_duration(int(eta))}",
        )



@sentry_bind_user_max
@sentry_transaction(name="file.upload", op="max.message")
async def handle_max_file(message: aiomax.Message, bot: aiomax.Bot) -> None:
    """Handle incoming file/audio/video attachments from Max."""
    try:
        user_id = int(message.sender.user_id)
    except (ValueError, TypeError):
        logging.warning("Max: cannot parse user_id: %s", message.sender)
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

    # Path(...).name drops any user-supplied directories so the name cannot
    # escape the temp workdir (e.g. "../../x" or an absolute path).
    file_name = truncate_filename(Path(file_name).name)

    file_size = getattr(attachment, "size", None) or 0
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
    ack = await safe_send_message(bot, ack_text, chat_id=chat_id)
    if ack is None:
        return

    file_url = getattr(attachment, "url", None)
    if not file_url:
        await safe_send_message(bot, "❌ Не удалось получить файл от Max", chat_id=chat_id)
        return

    if mime and not is_supported_mime(mime):
        await safe_send_message(bot,
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

        download_ticker = None
        if show_progress:
            download_ticker = asyncio.create_task(
                _download_ticker(bot, ack.body.message_id, local_path, file_size)
            )
        try:
            downloaded = await download_max_file(file_url, local_path)
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
        if not downloaded:
            await safe_send_message(bot,
                "❌ Не удалось загрузить файл\n"
                "Пожалуйста, попробуйте ещё раз",
                chat_id=chat_id,
            )
            return

        if not show_progress:
            # Max attachments do not always carry a size — fall back to the
            # downloaded file so big files still get conversion progress.
            try:
                show_progress = local_path.stat().st_size > PROGRESS_THRESHOLD_BYTES
            except OSError:
                pass

        duration = await get_media_duration(local_path)
        if not duration:
            await safe_send_message(bot,
                "❌ Не удалось определить длительность файла\n"
                "Возможно, формат не поддерживается или файл повреждён",
                chat_id=chat_id,
            )
            return

        duration_str = format_duration(int(duration))
        if duration > MAX_AUDIO_DURATION:
            max_duration_str = format_duration(MAX_AUDIO_DURATION)
            await safe_send_message(bot,
                f"❌ Файл слишком длинный: {duration_str}\n"
                f"Максимально допустимая длительность — {max_duration_str}",
                chat_id=chat_id,
            )
            return

        price_for_user = max(MIN_PRICE_RUB, speechkit_provider.cost_in_rub(duration))
        # Not enough balance is no longer a dead end: the task is still
        # prepared, and a topup prompt follows the confirm message below.
        needs_topup = user.balance < price_for_user

        safe_stem = sanitize_filename(Path(file_name).stem)
        ogg_name = f"{safe_stem}.ogg"
        ogg_path = out_dir / ogg_name
        progress_path = out_dir / f"{safe_stem}.progress"

        ticker = None
        if show_progress:
            await safe_edit_message(bot, ack.body.message_id, "🎬 Извлекаю аудиодорожку…")
            ticker = asyncio.create_task(
                _conversion_ticker(bot, ack.body.message_id, progress_path, duration)
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
                    "❌ В этом файле не обнаружено аудио\n"
                    "Пожалуйста, отправьте файл со звуком"
                )
            elif convert_error == "moov_atom_not_found":
                error_text = (
                    "❌ Файл повреждён — запись была прервана и не сохранена до конца\n"
                    "Попробуйте записать снова"
                )
            else:
                error_text = (
                    "❌ Не удалось обработать файл\n"
                    "Возможно, он имеет неподдерживаемый формат"
                )
            await safe_send_message(bot, error_text, chat_id=chat_id)
            await upload_file(local_path, f"error/{user_id}/{message.body.message_id}_{local_path.name}")
            return

        try:
            if local_path.exists():
                local_path.unlink()
        except Exception:
            logging.exception("Could not remove original file %s", local_path)

        if show_progress:
            await safe_edit_message(bot, ack.body.message_id, "✨ Почти готово…")

        object_name = f"source/{user_id}/{message.body.message_id}_{ogg_path.name}"
        s3_url = await upload_file(ogg_path, object_name)
        if not s3_url:
            await safe_send_message(bot,
                "❌ Не удалось загрузить файл\n"
                "Пожалуйста, попробуйте ещё раз чуть позже",
                chat_id=chat_id,
            )
            return

    history = add_transcription(
        user_id=user_id,
        platform=PLATFORM_MAX,
        status=STATUS_PENDING,
        audio_s3_path=s3_url,
        provider=PROVIDER_REPLICATE,
        duration_seconds=int(duration),
        price_for_user=price_for_user,
        result_s3_path=None,
    )

    keyboard = make_confirm_keyboard(history.id)

    hint = "\n\n💡 Бот лучше всего работает с записями от 5 минут" if duration < 300 else ""
    details = (
        f"Длительность: {duration_str}\n"
        f"Стоимость: {price_for_user} ₽"
        f"{hint}"
    )
    confirm_msg = await safe_send_message(bot,
        f"<b>🎧 Аудио подготовлено</b>\n\n{details}",
        chat_id=chat_id,
        keyboard=keyboard,
        format="html",
    )
    if confirm_msg is None:
        # Max HTML formatting is unverified — never lose the confirm over styling.
        confirm_msg = await safe_send_message(bot,
            f"🎧 Аудио подготовлено\n\n{details}",
            chat_id=chat_id,
            keyboard=keyboard,
        )

    if confirm_msg is None:
        return

    update_transcription(history.id, message_id=str(confirm_msg.body.message_id))

    # The confirm message carries all the info — the staged ack is now clutter.
    await safe_delete_message(bot, ack.body.message_id)

    if needs_topup:
        await safe_send_message(bot,
            f"⚠️ На балансе не хватает средств\n"
            f"Баланс: {user.balance} ₽, стоимость: {price_for_user} ₽\n\n"
            f"Пополните баланс и нажмите «Распознать»",
            chat_id=chat_id,
            keyboard=make_topup_amounts_keyboard(),
        )
