"""Handler for /history command on Max messenger."""
import logging

import aiomax

from pathlib import Path

from aiomax.buttons import CallbackButton, KeyboardBuilder

from database.models import PLATFORM_MAX, STATUS_COMPLETED, is_owner
from database.queries import get_recent_transcriptions, get_transcription
from utils.s3 import download_text, object_name_from_url
from utils.utils import format_duration, MoscowTimezone
from utils.tg import STATUS_EMOJI, fmt_price
from utils.sentry import sentry_bind_user_max, sentry_transaction
from messengers.max import safe_callback_answer, safe_send_document, safe_send_message


@sentry_bind_user_max
@sentry_transaction(name="history", op="max.command")
async def handle_max_history(message: aiomax.Message, bot: aiomax.Bot) -> None:
    try:
        user_id = int(message.sender.user_id)
    except (ValueError, TypeError):
        logging.warning("Max: cannot parse user_id: %s", message.sender)
        return

    items = get_recent_transcriptions(user_id, PLATFORM_MAX, limit=10)

    if not items:
        await safe_send_message(bot,
            "История пуста\n\n"
            "Пришлите видео или аудио — вернём текст",
            chat_id=message.recipient.chat_id,
        )
        return

    lines: list[str] = []
    doc_buttons: list[CallbackButton] = []
    for r in items:
        status = r.status if isinstance(r.status, str) else ""
        emoji = STATUS_EMOJI[status] if status in STATUS_EMOJI else "•"
        dt = r.created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=MoscowTimezone)
        dt_str = dt.strftime("%d.%m %H:%M")
        dur = format_duration(r.duration_seconds)
        price_for_user = fmt_price(r.price_for_user)
        lines.append(f"{emoji} {dt_str} МСК • {dur} • {price_for_user}")
        if status == STATUS_COMPLETED and r.result_s3_path:
            doc_buttons.append(CallbackButton(f"📄 {dt_str} • {dur}", f"history_doc:{r.id}"))

    msg = (
        "Последние 10 распознаваний:\n"
        + "\n".join(lines)
        + "\n\nСтатусы: 🕓 ожидание • ⏳ в работе • ✅ готово • ❌ ошибка • 🚫 отменено"
    )

    keyboard = None
    if doc_buttons:
        msg += "\n\nГотовые тексты можно получить ещё раз:"
        keyboard = KeyboardBuilder()
        for btn in doc_buttons:
            keyboard = keyboard.row(btn)

    await safe_send_message(bot, msg, chat_id=message.recipient.chat_id, keyboard=keyboard)


@sentry_bind_user_max
@sentry_transaction(name="history.document", op="max.callback")
async def handle_max_history_doc(callback: aiomax.Callback, bot: aiomax.Bot) -> None:
    """Re-send a finished transcription document from S3."""
    await safe_callback_answer(callback, notification="")

    try:
        transcription_id = int(callback.payload.split(":", 1)[1])
        user_id = int(callback.user.user_id)
    except (IndexError, ValueError, TypeError, AttributeError):
        return

    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, user_id, PLATFORM_MAX):
        return
    if not transcription.result_s3_path:
        return

    object_name = object_name_from_url(transcription.result_s3_path)
    text = await download_text(object_name)
    if not text:
        await safe_send_message(bot,
            "❌ Не удалось получить текст\n\n"
            "Попробуйте ещё раз чуть позже",
            chat_id=callback.message.recipient.chat_id,
        )
        return

    await safe_send_document(bot, user_id, text.encode("utf-8"), Path(object_name).name, "")
