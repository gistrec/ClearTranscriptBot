"""Handler for the 'Create summary' button on completed transcriptions."""
from telegram import Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM
from database.queries import create_refinement, get_transcription, has_refinement
from utils.sentry import sentry_bind_user, sentry_transaction
from utils.utils import format_duration
from messengers.telegram import make_summarize_keyboard, safe_reply_text, safe_edit_message_reply_markup


@sentry_bind_user
@sentry_transaction(name="summarization.create", op="telegram.callback")
async def handle_summarize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    _, transcription_id_str = query.data.split(":")
    transcription_id = int(transcription_id_str)

    transcription = get_transcription(transcription_id)
    if transcription is None or transcription.user_id != query.from_user.id or transcription.user_platform != PLATFORM_TELEGRAM:
        return

    if not transcription.result_s3_path:
        return

    show_improve = not has_refinement(transcription_id, "improve")
    await safe_edit_message_reply_markup(
        query,
        reply_markup=make_summarize_keyboard(transcription_id, show_summarize=False, show_improve=show_improve),
    )
    msg = await safe_reply_text(
        query.message,
        f"⏳ Создаю конспект...\n\n"
        f"Время обработки: {format_duration(0)}"
    )

    if msg is None:
        await safe_reply_text(query.message, "Не удалось создать конспект")
        return

    create_refinement(
        transcription_id=transcription_id,
        user_id=transcription.user_id,
        platform=PLATFORM_TELEGRAM,
        message_id=str(msg.message_id),
    )
