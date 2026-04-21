"""python-telegram-bot helpers with error handling."""
import logging

from telegram.error import Forbidden


async def safe_send_message(bot, *args, **kwargs):
    try:
        return await bot.send_message(*args, **kwargs)
    except Forbidden as exc:
        logging.warning("TG send_message skipped (bot blocked): %s", exc)
        return None


async def safe_edit_message(bot, chat_id, message_id, text: str, reply_markup=None) -> None:
    try:
        await bot.edit_message_text(
            chat_id=int(chat_id),
            message_id=int(message_id),
            text=text,
            reply_markup=reply_markup,
        )
    except Exception:
        logging.exception(
            "TG edit_message failed chat=%s msg=%s text=%r",
            chat_id, message_id, text[:30],
        )


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
        logging.warning("TG send_document skipped (bot blocked) chat=%s: %s", chat_id, exc)
        return None
    except Exception:
        logging.exception("TG send_document failed chat=%s", chat_id)
        return None


async def safe_remove_keyboard(bot, chat_id, message_id) -> None:
    try:
        await bot.edit_message_reply_markup(
            chat_id=int(chat_id),
            message_id=int(message_id),
            reply_markup=None,
        )
    except Exception:
        logging.exception(
            "TG remove_keyboard failed chat=%s msg=%s", chat_id, message_id
        )
