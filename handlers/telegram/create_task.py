from decimal import Decimal
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM
from database.queries import (
    change_user_balance,
    get_transcription,
    get_user,
    update_transcription,
)

from utils.sentry import sentry_bind_user, sentry_transaction
from utils.utils import format_duration, MoscowTimezone
from utils.transcription import start_transcription, get_model_name


@sentry_bind_user
@sentry_transaction(name="transcription.create", op="telegram.callback")
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
    user_id = query.from_user.id

    if task is None or task.user_id != user_id or task.user_platform != PLATFORM_TELEGRAM:
        await query.edit_message_text("Задача не найдена")
        return

    if task.status != "pending":
        await query.edit_message_text("Задача уже запущена")
        return

    user = get_user(user_id, PLATFORM_TELEGRAM)
    if user is None:
        await query.edit_message_text("Пользователь не найден")
        return

    price_for_user = Decimal(task.price_for_user or 0)
    if user.balance < price_for_user:
        await query.edit_message_text(
            f"Недостаточно средств\n"
            f"Баланс: {user.balance} ₽, требуется: {price_for_user} ₽\n\n"
            f"Для пополнения баланса используйте команду /topup"
        )
        return

    change_user_balance(user_id, PLATFORM_TELEGRAM, -price_for_user)

    operation_id = await start_transcription(
        task.audio_s3_path,
        provider=task.provider,
        duration_seconds=task.duration_seconds,
    )
    if not operation_id:
        change_user_balance(user_id, PLATFORM_TELEGRAM, price_for_user)
        await query.edit_message_text(
            "Не удалось запустить распознавание\n"
            "Пожалуйста, попробуйте ещё раз чуть позже"
        )
        return

    audio_duration_str = format_duration(task.duration_seconds)
    elapsed_str = format_duration(0)
    await query.edit_message_text(
        f"⏳ Задача в работе\n\n"
        f"Длительность: {audio_duration_str}\n"
        f"Стоимость: {task.price_for_user} ₽\n\n"
        f"Время обработки: {elapsed_str}"
    )

    now = datetime.now(MoscowTimezone)
    model = get_model_name(task.provider, task.duration_seconds)

    update_transcription(
        task.id,
        status="running",
        operation_id=operation_id,
        message_id=str(query.message.message_id),
        model=model,
        started_at=now,
    )
