from telegram import Update
from telegram.ext import ContextTypes

from utils.sentry import sentry_bind_user, sentry_transaction
from messengers.telegram import safe_reply_text


@sentry_bind_user
@sentry_transaction(name="price", op="telegram.command")
async def handle_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await safe_reply_text(
        update.message,
        "Стоимость распознавания\n\n"
        "Цена — 0,01 ₽ за 1 секунду аудио, например:\n"
        "* 3 ₽ за 5 минут\n"
        "* 18 ₽ за 30 минут\n"
        "* 36 ₽ за 1 час\n\n"
        "Минимальная стоимость одного распознавания — 1 ₽",
    )
