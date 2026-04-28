"""Handler for the 'Улучшить текст' button on completed transcriptions."""
from telegram import Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM
from database.queries import create_refinement, get_transcription, has_refinement
from utils.sentry import sentry_bind_user, sentry_transaction
from utils.utils import format_duration, SUMMARIZE_THRESHOLD
from messengers.telegram import make_summarize_keyboard, make_send_as_text_keyboard, safe_reply_text, safe_edit_message_reply_markup


@sentry_bind_user
@sentry_transaction(name="improvement.create", op="telegram.callback")
async def handle_improve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    _, transcription_id_str = query.data.split(":")
    transcription_id = int(transcription_id_str)

    transcription = get_transcription(transcription_id)
    if transcription is None or transcription.user_id != query.from_user.id or transcription.user_platform != PLATFORM_TELEGRAM:
        return

    if not transcription.result_s3_path:
        return

    show_summarize = not has_refinement(transcription_id, "summarize")
    duration = transcription.duration_seconds or 0
    if duration > SUMMARIZE_THRESHOLD:
        remaining_keyboard = make_summarize_keyboard(transcription_id, show_summarize=show_summarize, show_improve=False)
    else:
        remaining_keyboard = make_send_as_text_keyboard(transcription_id, show_improve=False)
    await safe_edit_message_reply_markup(query, reply_markup=remaining_keyboard)
    msg = await safe_reply_text(
        query.message,
        f"⏳ Улучшаю текст...\n\n"
        f"Время обработки: {format_duration(0)}"
    )

    if msg is None:
        await safe_reply_text(query.message, "Не удалось улучшить текст")
        return

    create_refinement(
        transcription_id=transcription_id,
        user_id=transcription.user_id,
        platform=PLATFORM_TELEGRAM,
        message_id=str(msg.message_id),
        task_type="improve",
    )
