"""aiomax bot helpers with error handling."""
import logging
import aiomax

from typing import Optional

from aiomax.buttons import CallbackButton, KeyboardBuilder


class _MaxKeyboardAttachment:
    """Wraps an aiomax KeyboardBuilder as an attachment-like object.

    Workaround for an aiomax bug: send_message's AttachmentNotReady retry
    drops the keyboard= parameter, losing the inline keyboard. By encoding
    the keyboard as an element of attachments= it survives the retry.
    """
    def __init__(self, keyboard):
        if isinstance(keyboard, KeyboardBuilder):
            keyboard = keyboard.to_list()
        self._keyboard = keyboard

    def as_dict(self):
        return {
            "type": "inline_keyboard",
            "payload": {"buttons": self._keyboard},
        }


def _is_chat_denied(exc: Exception) -> bool:
    args = getattr(exc, "args", ())
    return bool(args) and args[0] == "chat.denied"


async def safe_callback_answer(callback: aiomax.Callback, **kwargs):
    try:
        return await callback.answer(**kwargs)
    except Exception as exc:
        if _is_chat_denied(exc):
            logging.warning("Max callback.answer skipped (suspended dialog): %s", exc)
            return None
        logging.exception("Max callback.answer failed user=%s", getattr(callback.user, "user_id", "?"))
        return None


async def safe_send_message(bot: aiomax.Bot, *args, **kwargs):
    try:
        return await bot.send_message(*args, **kwargs)
    except Exception as exc:
        if _is_chat_denied(exc):
            logging.warning("Max send_message skipped (suspended dialog): %s", exc)
            return None
        chat_id = kwargs.get("chat_id") or kwargs.get("user_id") or (args[1] if len(args) > 1 else "?")
        logging.exception("Max send_message failed chat=%s", chat_id)
        return None


_KEYBOARD_NOT_SET = object()


async def safe_edit_message(bot: aiomax.Bot, *args, keyboard=_KEYBOARD_NOT_SET, **kwargs):
    if keyboard is not _KEYBOARD_NOT_SET:
        kwargs["attachments"] = [_MaxKeyboardAttachment(keyboard)] if keyboard is not None else []
    try:
        return await bot.edit_message(*args, **kwargs)
    except Exception as exc:
        if _is_chat_denied(exc):
            logging.warning("Max edit_message skipped (suspended dialog): %s", exc)
            return None
        logging.exception("Max edit_message failed args=%s", args[:1])
        return None


async def safe_remove_keyboard(bot: aiomax.Bot, message_id):
    try:
        return await bot.edit_message(str(message_id), attachments=[])
    except Exception as exc:
        if _is_chat_denied(exc):
            logging.warning("Max remove_keyboard skipped (suspended dialog): %s", exc)
            return None
        logging.exception("Max remove_keyboard failed msg=%s", message_id)
        return None


def make_confirm_keyboard(task_id: int) -> KeyboardBuilder:
    return (
        KeyboardBuilder()
        .row(
            CallbackButton("Распознать", f"create_task:{task_id}"),
            CallbackButton("Отменить", f"cancel_task:{task_id}"),
        )
    )


def make_rating_keyboard(transcription_id: int, selected: int | None = None) -> KeyboardBuilder:
    buttons = [
        CallbackButton(
            f"✅ {i}⭐" if i == selected else f"{i}⭐",
            f"rate:{transcription_id}:{i}",
        )
        for i in range(1, 6)
    ]
    return KeyboardBuilder().row(*buttons)


def make_topup_amounts_keyboard() -> KeyboardBuilder:
    return (
        KeyboardBuilder()
        .row(
            CallbackButton("50 ₽", "topup:50"),
            CallbackButton("100 ₽", "topup:100"),
        )
        .row(
            CallbackButton("250 ₽", "topup:250"),
            CallbackButton("500 ₽", "topup:500"),
        )
        .row(CallbackButton("Отменить", "topup:cancel"))
    )


def make_payment_actions_keyboard(order_id: str) -> KeyboardBuilder:
    return (
        KeyboardBuilder()
        .row(CallbackButton("Проверить платёж", f"payment:check:{order_id}"))
        .row(CallbackButton("Отменить платёж", f"payment:cancel:{order_id}"))
    )


def make_summarize_keyboard(
    transcription_id: int,
    show_summarize: bool = True,
    show_improve: bool = True,
) -> Optional[KeyboardBuilder]:
    buttons = []
    if show_summarize:
        buttons.append(CallbackButton("📝 Создать конспект", f"summarize:{transcription_id}"))
    if show_improve:
        buttons.append(CallbackButton("✨ Улучшить текст", f"improve:{transcription_id}"))
    return KeyboardBuilder().row(*buttons) if buttons else None


def make_send_as_text_keyboard(
    transcription_id: int,
    show_send_as_text: bool = True,
    show_improve: bool = True,
) -> Optional[KeyboardBuilder]:
    buttons = []
    if show_send_as_text:
        buttons.append(CallbackButton("📄 Отправить текстом", f"send_as_text:{transcription_id}"))
    if show_improve:
        buttons.append(CallbackButton("✨ Улучшить текст", f"improve:{transcription_id}"))
    return KeyboardBuilder().row(*buttons) if buttons else None


async def safe_send_document(bot: aiomax.Bot, chat_id, data, filename: str, caption: str, keyboard=None):
    try:
        file_attachment = await bot.upload_file(data, filename)
        attachments = []
        if keyboard is not None:
            attachments.append(_MaxKeyboardAttachment(keyboard))
        attachments.append(file_attachment)
        return await bot.send_message(caption, user_id=int(chat_id), attachments=attachments)
    except Exception as exc:
        if _is_chat_denied(exc):
            logging.warning("Max send_document skipped (suspended dialog): %s", exc)
            return None
        logging.exception("Max send_document failed chat=%s", chat_id)
        return None
