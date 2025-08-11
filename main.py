"""Telegram bot for ClearTranscriptBot."""
import os
import shutil
import tempfile
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
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
    get_recent_transcriptions,
    change_user_balance,
)
from utils.ffmpeg import convert_to_ogg, get_media_duration
from utils.s3 import upload_file
from utils.speechkit import run_transcription, cost_yc_async_rub, available_time_by_balance
from utils.tg import STATUS_EMOJI, fmt_duration, fmt_price, extract_local_path
from scheduler import check_running_tasks
from decimal import Decimal
from zoneinfo import ZoneInfo
from datetime import timezone

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
USE_LOCAL_PTB = os.environ.get("USE_LOCAL_PTB") is not None

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN must be set")


async def register_commands(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Начать работу"),
            BotCommand("history", "История распознаваний"),
            BotCommand("balance", "Текущий баланс"),
            BotCommand("price", "Стоимость распознавания"),
        ]
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond to regular text messages."""
    telegram_id = update.message.from_user.id
    user = get_user_by_telegram_id(telegram_id)
    if user is None:
        user = add_user(telegram_id, update.message.from_user.username)
    balance = Decimal(user.balance or 0)
    minutes, seconds = available_time_by_balance(balance)
    if update.message.text and update.message.text.startswith("/start"):
        await update.message.reply_text(
            "Отправьте видео или аудио — вернём текст.\n"
            "Поддерживаем все популярные форматы:\n"
            "• Видео: mp4, mov, mkv, webm и другие\n"
            "• Аудио: mp3, m4a, wav, ogg/opus, flac и другие\n\n"
            f"Текущий баланс: {balance} ₽\n"
            f"Хватит на распознавание: {minutes} мин {seconds} сек\n\n"
            "Доступные команды:\n"
            "• /history — история распознаваний\n"
            "• /balance — текущий баланс\n"
            "• /price — стоимость"
        )
    else:
        await update.message.reply_text(
            f"Баланс: {balance} ₽\n"
            f"Хватит на распознавание {minutes} мин {seconds} сек.\n\n"
            "Отправьте видео или аудио, чтобы получить его трансрибацию"
        )


def _is_supported(mime: str) -> bool:
    return mime.startswith("audio/") or mime.startswith("video/")


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming media files."""
    message = update.message
    telegram_id = message.from_user.id
    user = get_user_by_telegram_id(telegram_id)
    if user is None:
        user = add_user(telegram_id, message.from_user.username)

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
        "Файл получен.\n\n"
        "Определяю длительность и стоимость перевода в текст. "
        "Скоро попрошу подтвердить запуск.",
    )

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

        duration = get_media_duration(local_path)
        price = cost_yc_async_rub(duration)
        price_dec = Decimal(price)
        if user.balance < price_dec:
            await message.reply_text(
                f"Недостаточно средств. Баланс: {user.balance} ₽, требуется: {price} ₽"
            )
            return

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
    user = get_user_by_telegram_id(telegram_id)
    if user is None:
        await query.edit_message_text("Пользователь не найден")
        return
    price = Decimal(task.price_rub or 0)
    if user.balance < price:
        await query.edit_message_text(
            f"Недостаточно средств. Баланс: {user.balance} ₽, требуется: {price} ₽"
        )
        return
    change_user_balance(telegram_id, -price)

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


async def handle_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    items = get_recent_transcriptions(telegram_id, limit=10)

    if not items:
        await update.message.reply_text(
            "История пуста. Пришлите видео или аудио — вернём текст."
        )
        return

    msk = ZoneInfo("Europe/Moscow")
    lines: list[str] = []
    for r in items:
        emoji = STATUS_EMOJI.get(r.status, "•")
        dt = r.created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(msk)
        dt_str = dt.strftime("%Y-%m-%d %H:%M")
        dur = fmt_duration(r.duration_seconds)
        price = fmt_price(r.price_rub)
        lines.append(f"{emoji} #{r.id} • {dt_str} МСК • {dur} • {price}")

    msg = (
        "Последние 10 распознаваний:\n"
        + "\n".join(lines)
        + "\n\nСтатусы: 🕓 ожидание • ⏳ в работе • ✅ готово • ❌ ошибка • 🚫 отменено"
    )

    await update.message.reply_text(msg)


async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    user = get_user_by_telegram_id(telegram_id)
    if user is None:
        user = add_user(telegram_id, update.effective_user.username)
    balance = Decimal(user.balance or 0)
    minutes, seconds = available_time_by_balance(balance)
    await update.message.reply_text(
        f"Текущий баланс: {balance} ₽\n"
        f"Хватит на распознавание: {minutes} мин {seconds} сек\n\n"
        "Для пополнения баланса напишите @gistrec"
    )


async def handle_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Мы используем Yandex SpeechKit (асинхронное распознавание файлов)\n"
        "Цена: 0,15 ₽ за каждые 15 секунд аудио\n\n"
        "<a href=\"https://yandex.cloud/ru/docs/speechkit/pricing#prices-stt\">"
        "Подробнее о тарификации Yandex SpeechKit</a>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def main() -> None:
    """Start the Telegram bot."""
    builder = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(register_commands)
    )
    if USE_LOCAL_PTB:
        builder = (
            builder.base_url("http://127.0.0.1:8081/bot{token}")
            .base_file_url("http://127.0.0.1:8081/file/bot{token}")
            .http_version("1.1")
            .get_updates_http_version("1.1")
        )
    application = builder.build()
    application.add_handler(CommandHandler("history", handle_history))
    application.add_handler(CommandHandler("balance", handle_balance))
    application.add_handler(CommandHandler("price", handle_price))
    application.add_handler(MessageHandler(filters.TEXT, handle_text))
    file_filters = filters.Document.ALL | filters.AUDIO | filters.VIDEO | filters.VOICE
    application.add_handler(MessageHandler(file_filters, handle_file))
    application.add_handler(
        CallbackQueryHandler(handle_create_task, pattern=r"^create_task:\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_cancel_task, pattern=r"^cancel_task:\d+$")
    )
    application.job_queue.run_repeating(check_running_tasks, interval=1.0)
    application.run_polling()


if __name__ == "__main__":
    main()
