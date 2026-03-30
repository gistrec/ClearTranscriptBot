"""Handler for the 'Create summary' button on completed transcriptions."""
from telegram import Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM
from database.queries import create_summarization, get_transcription
from utils.sentry import sentry_bind_user
from utils.utils import format_duration


SUMMARIZE_THRESHOLD = 300  # seconds — show button only for audio longer than this


@sentry_bind_user
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

    await query.edit_message_reply_markup(reply_markup=None)

    msg = await query.message.reply_text(
        f"⏳ Создаю конспект...\n\n"
        f"Время обработки: {format_duration(0)}"
    )

    create_summarization(
        transcription_id=transcription_id,
        user_id=transcription.user_id,
        platform=PLATFORM_TELEGRAM,
        message_id=str(msg.message_id),
    )
