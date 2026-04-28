"""Platform-agnostic message helpers; dispatch to the right messenger by platform."""
import messengers.telegram as tg_sender
import messengers.max as max_sender

from telegram import InputFile

from database.models import PLATFORM_TELEGRAM, PLATFORM_MAX


async def safe_send_message(context, platform: str, user_id, text: str) -> None:
    if platform == PLATFORM_TELEGRAM:
        return await tg_sender.safe_send_message(context.bot, chat_id=int(user_id), text=text)
    if platform == PLATFORM_MAX:
        max_bot = context.bot_data.get("max_bot")
        if max_bot is None:
            return
        await max_sender.safe_send_message(max_bot, text, user_id=int(user_id))


async def safe_edit_message(context, platform: str, user_id, message_id, text: str, tg_keyboard=None, max_keyboard=None) -> None:
    if platform == PLATFORM_TELEGRAM:
        await tg_sender.safe_edit_message(context.bot, user_id, message_id, text, tg_keyboard)
    if platform == PLATFORM_MAX:
        max_bot = context.bot_data.get("max_bot")
        if max_bot is None:
            return
        await max_sender.safe_edit_message(max_bot, str(message_id), text, keyboard=max_keyboard)


async def safe_remove_keyboard(context, platform: str, user_id, message_id) -> None:
    if platform == PLATFORM_TELEGRAM:
        await tg_sender.safe_remove_keyboard(context.bot, user_id, message_id)
    if platform == PLATFORM_MAX:
        max_bot = context.bot_data.get("max_bot")
        if max_bot is None:
            return
        await max_sender.safe_remove_keyboard(max_bot, message_id)


async def safe_send_document(context, platform: str, user_id, reply_to_message_id, data: bytes, filename: str, caption: str, tg_keyboard=None, max_keyboard=None) -> None:
    if platform == PLATFORM_TELEGRAM:
        await tg_sender.safe_send_document(
            context.bot, user_id, reply_to_message_id, InputFile(data, filename=filename), caption, tg_keyboard
        )
    if platform == PLATFORM_MAX:
        max_bot = context.bot_data.get("max_bot")
        if max_bot is None:
            return
        await max_sender.safe_send_document(max_bot, user_id, data, filename, caption, max_keyboard)
