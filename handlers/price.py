from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from utils.sentry import sentry_bind_user


@sentry_bind_user
async def handle_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Мы используем Yandex SpeechKit (асинхронное распознавание файлов)\n"
        "Цена: 0,15 ₽ за каждые 15 секунд аудио\n\n"
        "<a href=\"https://yandex.cloud/ru/docs/speechkit/pricing#prices-stt\">"
        "Подробнее о тарификации Yandex SpeechKit</a>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
