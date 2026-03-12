from decimal import Decimal
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from database.queries import (
    change_user_balance,
    get_transcription,
    get_user_by_telegram_id,
    update_transcription,
)

from utils.sentry import sentry_bind_user
from utils.utils import format_duration, MoscowTimezone
from utils.transcription import start_transcription


@sentry_bind_user
async def handle_create_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    try:
        _, id_str = query.data.split(":", 1)
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
            f"Недостаточно средств\n"
            f"Баланс: {user.balance} ₽, требуется: {price} ₽\n\n"
            f"Для пополнения баланса используйте команду /topup"
        )
        return

    change_user_balance(telegram_id, -price)

    operation_id = await start_transcription(
        task.audio_s3_path,
        provider=task.provider or "speechkit",
        duration_seconds=task.duration_seconds,
    )
    if not operation_id:
        change_user_balance(telegram_id, price)
        await query.edit_message_text(
            "Не удалось запустить распознавание\n"
            "Пожалуйста, попробуйте ещё раз чуть позже"
        )
        return

    await query.edit_message_reply_markup(reply_markup=None)

    duration_str = format_duration(0)
    status_message = await query.message.reply_text(
        f"🧠 Задача №{task_id} в работе\n\n"
        f"Прошло времени: {duration_str}\n\n"
        "Отправлю результат, как только всё будет готово"
    )

    now = datetime.now(MoscowTimezone)
    update_transcription(
        task.id,
        status="running",
        operation_id=operation_id,
        message_id=status_message.message_id,
        chat_id=status_message.chat_id,
        started_at=now,
    )
