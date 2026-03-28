"""Handler for the 'Распознать' callback button on Max messenger."""
import logging
from decimal import Decimal
from datetime import datetime

import aiomax

from database.models import PLATFORM_MAX
from database.queries import (
    change_user_balance,
    get_transcription,
    get_user,
    update_transcription,
)
from utils.utils import format_duration, MoscowTimezone
from utils.transcription import start_transcription, get_model_name
from utils.sentry import sentry_bind_user_max


@sentry_bind_user_max
async def handle_max_create_task(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await callback.answer(notification="")

    try:
        _, id_str = callback.payload.split(":", 1)
        task_id = int(id_str)
    except (ValueError, AttributeError):
        return

    try:
        user_id = int(callback.user.user_id)
    except (ValueError, TypeError, AttributeError):
        logging.error("Max create_task: cannot parse user_id from callback")
        return

    message_id = callback.message.body.message_id

    task = get_transcription(task_id)
    if task is None or task.user_id != user_id or task.platform != PLATFORM_MAX:
        await bot.edit_message(message_id, attachments=[], text="Задача не найдена")
        return

    if task.status != "pending":
        await bot.edit_message(message_id, attachments=[], text="Задача уже запущена")
        return

    user = get_user(user_id, PLATFORM_MAX)
    if user is None:
        await bot.edit_message(message_id, attachments=[], text="Пользователь не найден")
        return

    price_for_user = Decimal(task.price_for_user or 0)
    if user.balance < price_for_user:
        await bot.edit_message(
            message_id,
            f"Недостаточно средств\n"
            f"Баланс: {user.balance} ₽, требуется: {price_for_user} ₽\n\n"
            f"Для пополнения баланса используйте команду /topup",
            attachments=[],
        )
        return

    change_user_balance(user_id, PLATFORM_MAX, -price_for_user)

    operation_id = await start_transcription(
        task.audio_s3_path,
        provider=task.provider,
        duration_seconds=task.duration_seconds,
    )
    if not operation_id:
        change_user_balance(user_id, PLATFORM_MAX, price_for_user)
        await bot.edit_message(
            message_id,
            "Не удалось запустить распознавание\nПожалуйста, попробуйте ещё раз чуть позже",
            attachments=[],
        )
        return

    audio_duration_str = format_duration(task.duration_seconds)
    elapsed_str = format_duration(0)
    await bot.edit_message(
        message_id,
        f"⏳ Задача в работе\n\n"
        f"Длительность: {audio_duration_str}\n"
        f"Стоимость: {task.price_for_user} ₽\n\n"
        f"Время обработки: {elapsed_str}\n\n",
        attachments=[],
    )

    now = datetime.now(MoscowTimezone)
    model = get_model_name(task.provider, task.duration_seconds)

    update_transcription(
        task.id,
        status="running",
        operation_id=operation_id,
        message_id=message_id,
        model=model,
        started_at=now,
    )
