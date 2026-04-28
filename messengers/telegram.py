"""python-telegram-bot helpers with error handling."""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden

_MSG_NOT_MODIFIED = "Message is not modified"
_BOT_BLOCKED = "bot was blocked by the user"


async def safe_reply_text(message, *args, **kwargs):
    try:
        return await message.reply_text(*args, **kwargs)
    except Forbidden as exc:
        if _BOT_BLOCKED in exc.message.lower():
            logging.warning("TG reply_text skipped (bot blocked): %s", exc)
            return None
        logging.exception("TG reply_text failed")
        return None
    except Exception:
        logging.exception("TG reply_text failed")
        return None


async def safe_send_message(bot, *args, **kwargs):
    try:
        return await bot.send_message(*args, **kwargs)
    except Forbidden as exc:
        if _BOT_BLOCKED in exc.message.lower():
            logging.warning("TG send_message skipped (bot blocked): %s", exc)
            return None
        logging.exception("TG send_message failed")
        return None
    except Exception:
        logging.exception("TG send_message failed")
        return None


async def safe_edit_message_text(query, *args, **kwargs):
    try:
        return await query.edit_message_text(*args, **kwargs)
    except Forbidden as exc:
        if _BOT_BLOCKED in exc.message.lower():
            logging.warning("TG edit_message_text skipped (bot blocked): %s", exc)
            return None
        logging.exception("TG edit_message_text failed")
        return None
    except BadRequest as exc:
        if _MSG_NOT_MODIFIED in exc.message.lower():
            logging.warning("TG edit_message_text skipped (not modified): %s", exc)
            return None
        logging.exception("TG edit_message_text failed")
        return None
    except Exception:
        logging.exception("TG edit_message_text failed")
        return None


async def safe_edit_message_caption(query, *args, **kwargs):
    try:
        return await query.edit_message_caption(*args, **kwargs)
    except Forbidden as exc:
        if _BOT_BLOCKED in exc.message.lower():
            logging.warning("TG edit_message_caption skipped (bot blocked): %s", exc)
            return None
        logging.exception("TG edit_message_caption failed")
        return None
    except BadRequest as exc:
        if _MSG_NOT_MODIFIED in exc.message.lower():
            logging.info("TG edit_message_caption skipped (not modified): %s", exc)
            return None
        logging.exception("TG edit_message_caption failed")
        return None
    except Exception:
        logging.exception("TG edit_message_caption failed")
        return None


async def safe_edit_message(bot, chat_id, message_id, text: str, reply_markup=None):
    try:
        return await bot.edit_message_text(
            chat_id=int(chat_id),
            message_id=int(message_id),
            text=text,
            reply_markup=reply_markup,
        )
    except BadRequest as exc:
        if _MSG_NOT_MODIFIED in exc.message.lower():
            logging.info("TG edit_message skipped (not modified): %s", exc)
            return None
        logging.exception("TG edit_message failed")
        return None
    except Exception:
        logging.exception("TG edit_message failed")
        return None


async def safe_send_document(bot, chat_id, reply_to_message_id, document, caption: str, reply_markup=None, **kwargs):
    try:
        return await bot.send_document(
            chat_id=int(chat_id),
            reply_to_message_id=int(reply_to_message_id),
            document=document,
            caption=caption,
            reply_markup=reply_markup,
            **kwargs,
        )
    except Forbidden as exc:
        if _BOT_BLOCKED in exc.message.lower():
            logging.warning("TG send_document skipped (bot blocked) chat=%s: %s", chat_id, exc)
            return None
        logging.exception("TG send_document failed")
        return None
    except Exception:
        logging.exception("TG send_document failed")
        return None


async def safe_edit_message_reply_markup(query, *args, **kwargs):
    try:
        return await query.edit_message_reply_markup(*args, **kwargs)
    except Forbidden as exc:
        if _BOT_BLOCKED in exc.message.lower():
            logging.warning("TG edit_message_reply_markup skipped (bot blocked): %s", exc)
        else:
            logging.exception("TG edit_message_reply_markup failed (Forbidden): %s", exc)
        return None
    except BadRequest as exc:
        if exc.message.startswith(_MSG_NOT_MODIFIED):
            return None
        logging.exception("TG edit_message_reply_markup failed")
        return None
    except Exception:
        logging.exception("TG edit_message_reply_markup failed")
        return None


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


def make_summarize_keyboard(transcription_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📝 Создать конспект", callback_data=f"summarize:{transcription_id}"),
    ]])


def make_send_as_text_keyboard(transcription_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📄 Отправить текстом", callback_data=f"send_as_text:{transcription_id}"),
    ]])


async def safe_remove_keyboard(bot, chat_id, message_id) -> None:
    try:
        await bot.edit_message_reply_markup(
            chat_id=int(chat_id),
            message_id=int(message_id),
            reply_markup=None,
        )
    except Exception:
        logging.exception("TG remove_keyboard failed")
