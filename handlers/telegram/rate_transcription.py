"""Handler for transcription rating buttons."""
from telegram import Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM, is_owner
from database.queries import get_transcription, update_transcription

from messengers.telegram import make_rating_keyboard, safe_edit_message_text, safe_query_answer, safe_send_message
from utils.sentry import sentry_bind_user, sentry_transaction
from utils.utils import RATING_PROMPT, FEEDBACK_PROMPT


@sentry_bind_user
@sentry_transaction(name="transcription.rate", op="telegram.callback")
async def handle_rate_transcription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_query_answer(query, "Спасибо за оценку!")

    _, transcription_id_str, rating_str = query.data.split(":")
    transcription_id = int(transcription_id_str)
    rating = int(rating_str)

    transcription = get_transcription(transcription_id)
    if not is_owner(transcription, query.from_user.id, PLATFORM_TELEGRAM):
        return

    update_transcription(transcription_id, rating=rating)

    await safe_edit_message_text(
        query,
        text=RATING_PROMPT,
        reply_markup=make_rating_keyboard(transcription_id, selected=rating),
    )

    if rating <= 2:
        if context.user_data is not None:
            context.user_data["awaiting_feedback_for"] = transcription_id
        await safe_send_message(context.bot, chat_id=query.from_user.id, text=FEEDBACK_PROMPT)
