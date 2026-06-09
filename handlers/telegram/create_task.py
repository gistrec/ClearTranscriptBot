from decimal import Decimal
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM, is_owner
from database.queries import (
    claim_and_charge_transcription,
    fail_transcription_and_refund,
    get_transcription,
    get_user,
    update_transcription,
)

from messengers.telegram import safe_edit_message_text, safe_query_answer
from utils.sentry import sentry_bind_user, sentry_transaction
from utils.utils import format_duration, MoscowTimezone
from utils.transcription import start_transcription, get_model_name


@sentry_bind_user
@sentry_transaction(name="transcription.create", op="telegram.callback")
async def handle_create_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_query_answer(query)

    try:
        _, id_str = query.data.split(":", 1)
        task_id = int(id_str)
    except ValueError:
        await safe_edit_message_text(query, "Некорректная задача")
        return

    task = get_transcription(task_id)
    user_id = query.from_user.id

    if not is_owner(task, user_id, PLATFORM_TELEGRAM):
        await safe_edit_message_text(query, "Задача не найдена")
        return

    price_for_user = Decimal(task.price_for_user or 0)
    now = datetime.now(MoscowTimezone)
    model = get_model_name(task.provider, task.duration_seconds)

    outcome = claim_and_charge_transcription(
        task.id, now, model, str(query.message.message_id), price_for_user
    )
    if outcome == "not_pending":
        await safe_edit_message_text(query, "Задача уже запущена")
        return
    if outcome == "insufficient_funds":
        user = get_user(user_id, PLATFORM_TELEGRAM)
        await safe_edit_message_text(query,
            f"Недостаточно средств\n"
            f"Баланс: {user.balance} ₽, требуется: {price_for_user} ₽\n\n"
            f"Для пополнения баланса используйте команду /topup"
        )
        return

    operation_id = await start_transcription(
        task.audio_s3_path,
        provider=task.provider,
        duration_seconds=task.duration_seconds,
    )
    if not operation_id:
        fail_transcription_and_refund(task.id)
        await safe_edit_message_text(query,
            "Не удалось запустить распознавание\n"
            "Пожалуйста, попробуйте ещё раз чуть позже"
        )
        return

    # Record operation_id before the (slow) message edit: until it is written,
    # the task looks like a zombie to the scheduler's reaper.
    update_transcription(task.id, operation_id=operation_id)

    audio_duration_str = format_duration(task.duration_seconds)
    elapsed_str = format_duration(0)
    await safe_edit_message_text(query,
        f"⏳ Распознавание в процессе\n\n"
        f"Длительность: {audio_duration_str}\n"
        f"Стоимость: {task.price_for_user} ₽\n\n"
        f"Время обработки: {elapsed_str}"
    )
