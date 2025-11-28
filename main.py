"""Telegram bot for ClearTranscriptBot."""
import os
import logging

from telegram import BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from scheduler import check_running_tasks
from handlers.balance import handle_balance
from handlers.cancel_task import handle_cancel_task
from handlers.create_task import handle_create_task
from handlers.file import handle_file
from handlers.history import handle_history
from handlers.price import handle_price
from handlers.text import handle_text
from handlers.topup import handle_topup, handle_topup_callback, handle_check_payment, handle_cancel_payment


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
# Mute noisy loggers
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
USE_LOCAL_PTB = os.environ.get("USE_LOCAL_PTB") is not None

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN must be set")


async def register_commands(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Начать работу"),
            BotCommand("history", "История распознаваний"),
            BotCommand("balance", "Текущий баланс"),
            BotCommand("topup", "Пополнить баланс"),
            BotCommand("price", "Стоимость распознавания"),
        ]
    )


def main() -> None:
    """Start the Telegram bot."""
    builder = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(register_commands)
    )
    if USE_LOCAL_PTB:
        builder = (
            builder
            .base_url("http://127.0.0.1:8081/bot")
            .base_file_url("http://127.0.0.1:8081/file/bot")
            .local_mode(True)
        )
    application = builder.build()
    application.add_handler(CommandHandler("history", handle_history))
    application.add_handler(CommandHandler("balance", handle_balance))
    application.add_handler(CommandHandler("topup", handle_topup))
    application.add_handler(CommandHandler("price", handle_price))
    application.add_handler(MessageHandler(filters.TEXT, handle_text))
    file_filters = filters.Document.ALL | filters.AUDIO | filters.VIDEO | filters.VOICE
    application.add_handler(MessageHandler(file_filters, handle_file))
    application.add_handler(
        CallbackQueryHandler(handle_create_task, pattern=r"^create_task:\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_cancel_task, pattern=r"^cancel_task:\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_topup_callback, pattern=r"^topup:(cancel|\d+)$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_check_payment, pattern=r"^payment:check:.+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_cancel_payment, pattern=r"^payment:cancel:.+$")
    )
    application.job_queue.run_repeating(check_running_tasks, interval=1.0)
    application.run_polling()


if __name__ == "__main__":
    main()
