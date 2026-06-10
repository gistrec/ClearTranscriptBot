"""Platform-agnostic message helpers; dispatch to the right messenger by platform."""
import messengers.telegram as tg_sender
import messengers.max as max_sender

from telegram import InputFile

from database.models import PLATFORM_TELEGRAM, PLATFORM_MAX
from messengers.max import _MaxKeyboardAttachment


def _bold_first_line(text: str) -> str:
    # Both Telegram HTML and Max HTML understand <b>; texts passed here must
    # not contain unescaped < > & in dynamic parts.
    head, sep, rest = text.partition("\n")
    return f"<b>{head}</b>{sep}{rest}"


async def safe_send_message(context, platform: str, user_id, text: str) -> None:
    if platform == PLATFORM_TELEGRAM:
        await tg_sender.safe_send_message(context.bot, chat_id=int(user_id), text=text)
    if platform == PLATFORM_MAX:
        max_bot = context.bot_data.get("max_bot")
        if max_bot is None:
            return
        await max_sender.safe_send_message(max_bot, text, user_id=int(user_id))


async def safe_send_message_with_keyboard(context, platform: str, user_id, text: str, tg_keyboard=None, max_keyboard=None) -> None:
    if platform == PLATFORM_TELEGRAM:
        await tg_sender.safe_send_message(context.bot, chat_id=int(user_id), text=text, reply_markup=tg_keyboard)
    if platform == PLATFORM_MAX:
        max_bot = context.bot_data.get("max_bot")
        if max_bot is None:
            return
        attachments = [_MaxKeyboardAttachment(max_keyboard)] if max_keyboard is not None else None
        await max_sender.safe_send_message(max_bot, text, user_id=int(user_id), attachments=attachments)


async def safe_edit_message(context, platform: str, user_id, message_id, text: str, tg_keyboard=None, max_keyboard=None, bold_header: bool = False) -> None:
    if platform == PLATFORM_TELEGRAM:
        if bold_header:
            await tg_sender.safe_edit_message(context.bot, user_id, message_id, _bold_first_line(text), tg_keyboard, parse_mode="HTML")
        else:
            await tg_sender.safe_edit_message(context.bot, user_id, message_id, text, tg_keyboard)
    if platform == PLATFORM_MAX:
        max_bot = context.bot_data.get("max_bot")
        if max_bot is None:
            return
        if bold_header:
            sent = await max_sender.safe_edit_message(max_bot, str(message_id), _bold_first_line(text), keyboard=max_keyboard, format="html")
            if sent is not None:
                return
            # Max HTML formatting is unverified — never lose a status update over styling.
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
