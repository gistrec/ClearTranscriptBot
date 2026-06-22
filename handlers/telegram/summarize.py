"""Handler for the 'Create summary' button on completed transcriptions."""
from telegram import Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM, PROVIDER_REPLICATE, is_owner
from database.queries import create_refinement, get_transcription, has_refinement
from utils.sentry import sentry_bind_user, sentry_transaction
from utils.utils import format_duration
from messengers.telegram import make_summarize_keyboard, safe_query_answer, safe_reply_text, safe_edit_message_reply_markup


@sentry_bind_user
@sentry_transaction(name="summarization.create", op="telegram.callback")
async def handle_summarize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_query_answer(query)

    _, transcription_id_str = query.data.split(":")
    transcription_id = int(transcription_id_str)

    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, query.from_user.id, PLATFORM_TELEGRAM):
        return

    if not transcription.result_json:
        return

    if has_refinement(transcription_id, "summarize"):
        return

    show_improve = not has_refinement(transcription_id, "improve")
    show_timecodes = transcription.provider == PROVIDER_REPLICATE
    await safe_edit_message_reply_markup(
        query,
        reply_markup=make_summarize_keyboard(transcription_id, show_summarize=False, show_improve=show_improve, show_timecodes=show_timecodes),
    )
    msg = await safe_reply_text(
        query.message,
        f"⏳ Создаю конспект...\n\n"
        f"Время обработки: {format_duration(0)}"
    )

    if msg is None:
        await safe_reply_text(query.message, "❌ Не удалось создать конспект")
        return

    create_refinement(
        transcription_id=transcription_id,
        user_id=transcription.user_id,
        platform=PLATFORM_TELEGRAM,
        message_id=str(msg.message_id),
    )
