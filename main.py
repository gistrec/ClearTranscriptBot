"""Bot entry point — starts Telegram and Max bots concurrently."""
import aiomax
import asyncio
import logging
import os

from telegram import BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from schedulers.summarization import check_summarizations
from schedulers.transcription import check_running_tasks
from schedulers.topup import check_pending_payments

from handlers.telegram.balance import handle_balance
from handlers.telegram.cancel_task import handle_cancel_task
from handlers.telegram.create_task import handle_create_task
from handlers.telegram.file import handle_file
from handlers.telegram.history import handle_history
from handlers.telegram.price import handle_price
from handlers.telegram.text import handle_text
from handlers.telegram.topup import handle_topup, handle_topup_callback, handle_check_payment, handle_cancel_payment
from handlers.telegram.rate_transcription import handle_rate_transcription
from handlers.telegram.summarize import handle_summarize
from handlers.telegram.send_as_text import handle_send_as_text

from handlers.max.balance import handle_max_balance
from handlers.max.cancel_task import handle_max_cancel_task
from handlers.max.create_task import handle_max_create_task
from handlers.max.file import handle_max_file
from handlers.max.history import handle_max_history
from handlers.max.price import handle_max_price
from handlers.max.rate_transcription import handle_max_rate
from handlers.max.summarize import handle_max_summarize
from handlers.max.send_as_text import handle_max_send_as_text
from handlers.max.text import handle_max_text
from handlers.max.topup import (
    handle_max_topup,
    handle_max_topup_callback,
    handle_max_check_payment,
    handle_max_cancel_payment,
)

from messengers.common import BotSender
from healthcheck import start_healthcheck_server


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
# Mute noisy loggers
logging.getLogger("apscheduler").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.WARNING)


MAX_BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
USE_LOCAL_PTB = os.environ.get("USE_LOCAL_PTB") is not None
ENABLE_HEALTHCHECK = os.environ.get("ENABLE_HEALTHCHECK") == "1"

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


async def run_bots() -> None:
    """Start Telegram and (optionally) Max bots in the same event loop."""
    # --- Build PTB application ---
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

    # Register Telegram handlers
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
    application.add_handler(
        CallbackQueryHandler(handle_rate_transcription, pattern=r"^rate:\d+:[1-5]$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_summarize, pattern=r"^summarize:\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_send_as_text, pattern=r"^send_as_text:\d+$")
    )

    # --- Build Max bot (optional) ---
    max_bot = None
    if MAX_BOT_TOKEN:
        max_bot = aiomax.Bot(access_token=MAX_BOT_TOKEN)

        @max_bot.on_ready()
        async def _on_max_ready() -> None:
            await max_bot.patch_me(commands=[
                aiomax.BotCommand("history", "История распознаваний"),
                aiomax.BotCommand("balance", "Текущий баланс"),
                aiomax.BotCommand("topup", "Пополнить баланс"),
                aiomax.BotCommand("price", "Стоимость распознавания"),
            ])
            logging.info("Max bot commands registered")

        @max_bot.on_bot_start()
        async def _on_max_bot_start(event) -> None:
            print(event)
            logging.info("Max bot_start from user_id=%s", getattr(event, "user_id", "?"))
            from database.models import PLATFORM_MAX
            from database.queries import add_user, get_user
            from utils.utils import available_time_by_balance
            from decimal import Decimal
            try:
                user_id = int(event.user_id)
            except (ValueError, TypeError):
                return
            user = get_user(user_id, PLATFORM_MAX)
            if user is None:
                user = add_user(user_id, PLATFORM_MAX)
            balance = Decimal(user.balance or 0)
            duration_str = available_time_by_balance(balance)
            await event.send(
                "Отправьте видео или аудио — вернём текст\n\n"
                "Поддерживаем все популярные форматы:\n"
                "• Видео: mp4, mov, mkv, webm и другие\n"
                "• Аудио: mp3, m4a, wav, ogg/opus, flac и другие\n\n"
                f"Текущий баланс: {balance} ₽\n"
                f"Хватит на распознавание: {duration_str}\n\n"
                "Доступные команды:\n"
                "• /history — история распознаваний\n"
                "• /balance — текущий баланс\n"
                "• /topup — пополнить баланс\n"
                "• /price — стоимость"
            )

        @max_bot.on_message()
        async def _on_max_message(message: aiomax.Message) -> None:
            logging.info(
                "Max message from user_id=%s text=%r attachments=%s",
                getattr(message.sender, "user_id", "?"),
                (message.body.text or "")[:100],
                [type(a).__name__ for a in (message.body.attachments or [])],
            )
            _file_types = ("FileAttachment", "AudioAttachment", "VideoAttachment")
            _all_atts = list(message.body.attachments or [])
            _linked = getattr(message.link, "message", None)
            if _linked:
                _all_atts += list(_linked.attachments or [])
            if any(type(a).__name__ in _file_types for a in _all_atts):
                await handle_max_file(message, max_bot)
                return
            await handle_max_text(message, max_bot)

        @max_bot.on_button_callback()
        async def _on_max_callback(callback: aiomax.Callback) -> None:
            payload = callback.payload or ""
            if payload.startswith("create_task:"):
                await handle_max_create_task(callback, max_bot)
            elif payload.startswith("cancel_task:"):
                await handle_max_cancel_task(callback, max_bot)
            elif payload.startswith("rate:"):
                await handle_max_rate(callback, max_bot)
            elif payload.startswith("summarize:"):
                await handle_max_summarize(callback, max_bot)
            elif payload.startswith("send_as_text:"):
                await handle_max_send_as_text(callback, max_bot)
            elif payload.startswith("topup:"):
                await handle_max_topup_callback(callback, max_bot)
            elif payload.startswith("payment:check:"):
                await handle_max_check_payment(callback, max_bot)
            elif payload.startswith("payment:cancel:"):
                await handle_max_cancel_payment(callback, max_bot)

        @max_bot.on_command("balance")
        async def _cmd_balance(message: aiomax.Message) -> None:
            await handle_max_balance(message, max_bot)

        @max_bot.on_command("history")
        async def _cmd_history(message: aiomax.Message) -> None:
            await handle_max_history(message, max_bot)

        @max_bot.on_command("topup")
        async def _cmd_topup(message: aiomax.Message) -> None:
            await handle_max_topup(message, max_bot)

        @max_bot.on_command("price")
        async def _cmd_price(message: aiomax.Message) -> None:
            await handle_max_price(message, max_bot)

    # --- Wire BotSender into PTB bot_data ---
    sender = BotSender(tg_bot=application.bot, max_bot=max_bot)
    application.bot_data["sender"] = sender

    # Register job queue
    application.job_queue.run_repeating(check_running_tasks, interval=1.0)
    application.job_queue.run_repeating(check_summarizations, interval=1.0)
    application.job_queue.run_repeating(check_pending_payments, interval=10.0)

    # --- Start PTB (non-blocking) ---
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    # --- Start Max polling + healthcheck concurrently ---
    tasks = []
    if max_bot is not None:
        logging.info("Starting Max bot polling...")
        tasks.append(max_bot.start_polling())
    else:
        logging.info("MAX_BOT_TOKEN not set; running Telegram only. Press Ctrl+C to stop.")
        tasks.append(asyncio.Event().wait())
    if ENABLE_HEALTHCHECK:
        tasks.append(start_healthcheck_server())
    try:
        await asyncio.gather(*tasks)
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


def main() -> None:
    """Start the bot(s)."""
    asyncio.run(run_bots())


if __name__ == "__main__":
    main()
