"""python-telegram-bot helpers with error handling."""
import logging

from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden

_MSG_NOT_MODIFIED = "message is not modified"
_BOT_BLOCKED = "bot was blocked by the user"
_QUERY_TOO_OLD = "query is too old"
_CHAT_NOT_FOUND = "chat not found"


async def safe_query_answer(query, *args, **kwargs):
    try:
        return await query.answer(*args, **kwargs)
    except BadRequest as exc:
        if _QUERY_TOO_OLD in exc.message.lower():
            logging.warning("TG query.answer skipped (too old): %s", exc)
            return None
        logging.exception("TG query.answer failed")
        return None
    except Exception:
        logging.exception("TG query.answer failed")
        return None


async def safe_reply_text(message, *args, **kwargs):
    try:
        return await message.reply_text(*args, **kwargs)
    except Forbidden as exc:
        if _BOT_BLOCKED in exc.message.lower():
            logging.warning("TG reply_text skipped (bot blocked): %s", exc)
            return None
        logging.exception("TG reply_text failed")
        return None
    except BadRequest as exc:
        if _CHAT_NOT_FOUND in exc.message.lower():
            logging.warning("TG reply_text skipped (chat not found): %s", exc)
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
    except BadRequest as exc:
        if _CHAT_NOT_FOUND in exc.message.lower():
            logging.warning("TG send_message skipped (chat not found): %s", exc)
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


async def safe_send_document(bot, chat_id, reply_to_message_id, document, caption: str, reply_markup=None):
    try:
        return await bot.send_document(
            chat_id=int(chat_id),
            reply_to_message_id=int(reply_to_message_id) if reply_to_message_id is not None else None,
            # The user may have deleted the status message; deliver the paid
            # result anyway instead of failing on the dangling reply.
            allow_sending_without_reply=True,
            document=document,
            caption=caption,
            reply_markup=reply_markup,
            connect_timeout=15,
            write_timeout=30,
        )
    except Forbidden as exc:
        if _BOT_BLOCKED in exc.message.lower():
            logging.warning("TG send_document skipped (bot blocked) chat=%s: %s", chat_id, exc)
            return None
        logging.exception("TG send_document failed")
        return None
    except BadRequest as exc:
        if _CHAT_NOT_FOUND in exc.message.lower():
            logging.warning("TG send_document skipped (chat not found) chat=%s: %s", chat_id, exc)
            return None
        logging.exception("TG send_document failed")
        return None
    except Exception:
        logging.exception("TG send_document failed")
        return None


async def safe_delete_message(bot, chat_id, message_id):
    try:
        return await bot.delete_message(chat_id=int(chat_id), message_id=int(message_id))
    except Forbidden as exc:
        if _BOT_BLOCKED in exc.message.lower():
            logging.warning("TG delete_message skipped (bot blocked): %s", exc)
            return None
        logging.exception("TG delete_message failed")
        return None
    except Exception:
        logging.exception("TG delete_message failed")
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
        if exc.message.lower().startswith(_MSG_NOT_MODIFIED):
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


def make_summarize_keyboard(
    transcription_id: int,
    show_summarize: bool = True,
    show_improve: bool = True,
    show_timecodes: bool = False,
) -> Optional[InlineKeyboardMarkup]:
    buttons = []
    if show_summarize:
        buttons.append(InlineKeyboardButton("📝 Создать конспект", callback_data=f"summarize:{transcription_id}"))
    if show_timecodes:
        buttons.append(InlineKeyboardButton("⏱ С таймкодами", callback_data=f"tc:{transcription_id}"))
    if show_improve:
        buttons.append(InlineKeyboardButton("✏️ Знаки препинания и абзацы", callback_data=f"improve:{transcription_id}"))
    return InlineKeyboardMarkup([[btn] for btn in buttons]) if buttons else None


def make_send_as_text_keyboard(
    transcription_id: int,
    show_send_as_text: bool = True,
    show_improve: bool = True,
    show_timecodes: bool = False,
) -> Optional[InlineKeyboardMarkup]:
    buttons = []
    if show_send_as_text:
        buttons.append(InlineKeyboardButton("📄 Отправить текстом", callback_data=f"send_as_text:{transcription_id}"))
    if show_timecodes:
        buttons.append(InlineKeyboardButton("⏱ С таймкодами", callback_data=f"tc:{transcription_id}"))
    if show_improve:
        buttons.append(InlineKeyboardButton("✏️ Знаки препинания и абзацы", callback_data=f"improve:{transcription_id}"))
    return InlineKeyboardMarkup([[btn] for btn in buttons]) if buttons else None


def make_timecodes_format_keyboard(transcription_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 .txt с таймкодами", callback_data=f"tc_fmt:{transcription_id}:txt")],
        [InlineKeyboardButton("🎬 .srt субтитры", callback_data=f"tc_fmt:{transcription_id}:srt")],
        [InlineKeyboardButton("🎞 .vtt", callback_data=f"tc_fmt:{transcription_id}:vtt")],
        [InlineKeyboardButton("← Назад", callback_data=f"tc_back:{transcription_id}")],
    ])


def make_topup_amounts_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="50 ₽",  callback_data="topup:50"),
            InlineKeyboardButton(text="100 ₽", callback_data="topup:100"),
        ],
        [
            InlineKeyboardButton(text="250 ₽", callback_data="topup:250"),
            InlineKeyboardButton(text="500 ₽", callback_data="topup:500"),
        ],
        [
            InlineKeyboardButton(text="Отменить", callback_data="topup:cancel")
        ]
    ]
    return InlineKeyboardMarkup(buttons)


async def safe_remove_keyboard(bot, chat_id, message_id) -> None:
    try:
        await bot.edit_message_reply_markup(
            chat_id=int(chat_id),
            message_id=int(message_id),
            reply_markup=None,
        )
    except Exception:
        logging.exception("TG remove_keyboard failed")
