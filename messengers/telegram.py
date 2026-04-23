"""python-telegram-bot helpers with error handling."""
import logging

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


async def safe_remove_keyboard(bot, chat_id, message_id) -> None:
    try:
        await bot.edit_message_reply_markup(
            chat_id=int(chat_id),
            message_id=int(message_id),
            reply_markup=None,
        )
    except Exception:
        logging.exception("TG remove_keyboard failed")
