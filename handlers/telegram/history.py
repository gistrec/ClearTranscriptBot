from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM, STATUS_COMPLETED, is_owner
from database.queries import get_recent_transcriptions, get_transcription

from utils.s3 import download_text, object_name_from_url
from utils.sentry import sentry_bind_user, sentry_transaction
from utils.utils import format_duration, MoscowTimezone
from utils.tg import STATUS_EMOJI, fmt_price
from messengers.telegram import safe_query_answer, safe_reply_text, safe_send_document


@sentry_bind_user
@sentry_transaction(name="history", op="telegram.command")
async def handle_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    items = get_recent_transcriptions(user_id, PLATFORM_TELEGRAM, limit=10)

    if not items:
        await safe_reply_text(
            update.message,
            "История пуста\n\n"
            "Пришлите видео или аудио — вернём текст"
        )
        return


    lines: list[str] = []
    buttons: list[list[InlineKeyboardButton]] = []
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
            buttons.append([InlineKeyboardButton(
                f"📄 {dt_str} • {dur}", callback_data=f"history_doc:{r.id}"
            )])

    msg = (
        "Последние 10 распознаваний:\n"
        + "\n".join(lines)
        + "\n\nСтатусы: 🕓 ожидание • ⏳ в работе • ✅ готово • ❌ ошибка • 🚫 отменено"
    )
    if buttons:
        msg += "\n\nГотовые тексты можно получить ещё раз:"

    await safe_reply_text(
        update.message, msg,
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
    )


@sentry_bind_user
@sentry_transaction(name="history.document", op="telegram.callback")
async def handle_history_doc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Re-send a finished transcription document from S3."""
    query = update.callback_query
    await safe_query_answer(query)

    transcription_id = int(query.data.split(":", 1)[1])
    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, query.from_user.id, PLATFORM_TELEGRAM):
        return
    if not transcription.result_s3_path:
        return

    object_name = object_name_from_url(transcription.result_s3_path)
    text = await download_text(object_name)
    if not text:
        await safe_reply_text(
            query.message,
            "Не удалось получить текст\n"
            "Попробуйте ещё раз чуть позже"
        )
        return

    await safe_send_document(
        context.bot,
        query.message.chat_id,
        query.message.message_id,
        InputFile(text.encode("utf-8"), filename=Path(object_name).name),
        "",
    )
