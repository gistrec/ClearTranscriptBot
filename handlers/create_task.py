from decimal import Decimal

from telegram import Update
from telegram.ext import ContextTypes

from database.queries import (
    change_user_balance,
    get_transcription,
    get_user_by_telegram_id,
    update_transcription,
)
from utils.speechkit import run_transcription


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
