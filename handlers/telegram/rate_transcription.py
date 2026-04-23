"""Handler for transcription rating buttons."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from database.queries import get_transcription, update_transcription

from messengers.telegram import safe_edit_message_caption, safe_send_message
from utils.sentry import sentry_bind_user, sentry_transaction

FEEDBACK_PROMPT = "Расскажите, что пошло не так? Напишите пару слов — это поможет улучшить распознавание"


RATING_PROMPT = "Оцените качество распознавания"


def make_rating_keyboard(
    transcription_id: int,
    selected: int | None = None,
    show_summarize: bool = False,
) -> InlineKeyboardMarkup:
    rating_buttons = [
        InlineKeyboardButton(
            f"✅ {i}⭐" if i == selected else f"{i}⭐",
            callback_data=f"rate:{transcription_id}:{i}",
        )
        for i in range(1, 6)
    ]
    rows = [rating_buttons]
    if show_summarize:
        rows.append([
            InlineKeyboardButton("📝 Создать конспект", callback_data=f"summarize:{transcription_id}")
        ])
    return InlineKeyboardMarkup(rows)


@sentry_bind_user
@sentry_transaction(name="transcription.rate", op="telegram.callback")
async def handle_rate_transcription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Спасибо за оценку!")

    _, transcription_id_str, rating_str = query.data.split(":")
    transcription_id = int(transcription_id_str)
    rating = int(rating_str)

    transcription = get_transcription(transcription_id)
    if transcription is None or transcription.user_id != query.from_user.id:
        return

    update_transcription(transcription_id, rating=rating)

    await safe_edit_message_caption(
        query,
        caption=RATING_PROMPT,
        reply_markup=make_rating_keyboard(transcription_id, selected=rating),
    )

    if rating <= 3:
        if context.user_data is not None:
            context.user_data["awaiting_feedback_for"] = transcription_id
        await safe_send_message(context.bot, chat_id=query.from_user.id, text=FEEDBACK_PROMPT)
