"""Handler for the 'Распознать' callback button on Max messenger."""
import logging
from decimal import Decimal
from datetime import datetime

import aiomax

from database.models import PLATFORM_MAX, is_owner
from database.queries import (
    claim_and_charge_transcription,
    fail_transcription_and_refund,
    get_transcription,
    get_user,
    update_transcription,
)
from utils.utils import format_duration, MoscowTimezone
from utils.transcription import start_transcription, get_model_name
from utils.sentry import sentry_bind_user_max, sentry_transaction
from messengers.max import make_topup_amounts_keyboard, safe_callback_answer, safe_edit_message, safe_send_message


@sentry_bind_user_max
@sentry_transaction(name="transcription.create", op="max.callback")
async def handle_max_create_task(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    await safe_callback_answer(callback, notification="")

    try:
        _, id_str = callback.payload.split(":", 1)
        task_id = int(id_str)
    except (ValueError, AttributeError):
        return

    try:
        user_id = int(callback.user.user_id)
    except (ValueError, TypeError, AttributeError):
        logging.warning("Max create_task: cannot parse user_id from callback")
        return

    message_id = callback.message.body.message_id

    task = get_transcription(task_id)
    if not is_owner(task, user_id, PLATFORM_MAX):
        await safe_edit_message(bot, message_id, "Задача не найдена", attachments=[])
        return

    price_for_user = Decimal(task.price_for_user or 0)
    now = datetime.now(MoscowTimezone)
    model = get_model_name(task.provider, task.duration_seconds)

    outcome = claim_and_charge_transcription(
        task.id, now, model, str(message_id), price_for_user
    )
    if outcome == "not_pending":
        await safe_edit_message(bot, message_id, "Задача уже запущена", attachments=[])
        return
    if outcome == "insufficient_funds":
        user = get_user(user_id, PLATFORM_MAX)
        # Send a new message instead of editing: the original message keeps
        # its button, so after a topup the user can press it again.
        await safe_send_message(bot,
            f"❌ Недостаточно средств\n"
            f"Баланс: {user.balance} ₽, требуется: {price_for_user} ₽\n\n"
            f"Пополните баланс и нажмите «Распознать» ещё раз",
            chat_id=callback.message.recipient.chat_id,
            keyboard=make_topup_amounts_keyboard(),
        )
        return

    operation_id = await start_transcription(
        task.audio_s3_path,
        provider=task.provider,
        duration_seconds=task.duration_seconds,
    )
    if not operation_id:
        fail_transcription_and_refund(task.id)
        await safe_edit_message(bot,
            message_id,
            "❌ Не удалось запустить распознавание\n\n"
            "Деньги вернули на баланс, попробуйте ещё раз чуть позже",
            attachments=[],
        )
        return

    # Record operation_id before the (slow) message edit: until it is written,
    # the task looks like a zombie to the scheduler's reaper.
    update_transcription(task.id, operation_id=operation_id)

    audio_duration_str = format_duration(task.duration_seconds)
    elapsed_str = format_duration(0)
    await safe_edit_message(bot,
        message_id,
        f"⏳ Распознаём запись…\n\n"
        f"Длительность: {audio_duration_str}\n"
        f"Стоимость: {task.price_for_user} ₽\n\n"
        f"Время обработки: {elapsed_str}",
        attachments=[],
    )
