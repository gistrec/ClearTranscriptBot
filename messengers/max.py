"""aiomax bot helpers with error handling."""
import logging
import aiomax

from typing import Optional

from aiomax.buttons import CallbackButton, LinkButton, KeyboardBuilder
from aiomax.exceptions import ChatNotFound, InternalError


def patch_aiomax() -> None:
    """Apply runtime fixes for aiomax bugs that crash message parsing.

    1. LinkedMessage.from_json reads data["message"] unconditionally, but Max
       sends links without a message body (e.g. forwards), raising KeyError
       before any handler runs. Fall back to None, which MessageBody tolerates.
    2. CallbackButton.from_json reads data["intent"], but Max omits it in the
       message echoed back from a keyboard send, so parsing that response raises
       KeyError('intent') after the message was already delivered. Default to
       "default" (the constructor's own default) so the send returns normally.
    """
    from aiomax.types import LinkedMessage, MessageBody, User

    @staticmethod
    def _linked_message_from_json(data):
        if data is None:
            return None
        return LinkedMessage(
            type=data["type"],
            message=MessageBody.from_json(data.get("message")),
            sender=User.from_json(data.get("sender")),
            chat_id=data.get("chat_id"),
        )

    LinkedMessage.from_json = _linked_message_from_json

    @staticmethod
    def _callback_button_from_json(data):
        return CallbackButton(data["text"], data["payload"], data.get("intent", "default"))

    CallbackButton.from_json = _callback_button_from_json


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


# Max API conditions meaning the recipient is simply unreachable (dialog
# suspended, deleted, or never opened) — expected, not actionable bugs.
_DIALOG_GONE_CODES = ("chat.denied", "dialog.not.found")


def _is_dialog_unavailable(exc: Exception) -> bool:
    if isinstance(exc, ChatNotFound):
        return True
    args = getattr(exc, "args", ())
    return bool(args) and args[0] in _DIALOG_GONE_CODES


def _is_aiomax_null_raise(exc: Exception) -> bool:
    # aiomax/bot.py executes `raise await utils.get_exception(response)` for
    # 2xx responses whose body has success=false. get_exception returns None
    # for any 2xx status, so `raise None` surfaces as this TypeError.
    return (
        isinstance(exc, TypeError)
        and exc.args == ("exceptions must derive from BaseException",)
    )


def _is_aiomax_upload_failure(exc: Exception) -> bool:
    # aiomax.Bot.upload_file blindly reads raw_file["token"]; if Max's
    # upload endpoint returns an error response without the token key,
    # this surfaces as KeyError('token').
    return isinstance(exc, KeyError) and exc.args == ("token",)


def _log_aiomax_failure(label: str, ident: str, exc: Exception) -> None:
    """Log a known-noisy aiomax failure at warning, everything else at exception."""
    if _is_dialog_unavailable(exc):
        logging.warning("%s skipped %s (recipient unreachable): %s", label, ident, exc)
        return
    if isinstance(exc, InternalError):
        logging.warning("%s upstream error %s id=%s", label, ident, exc.id)
        return
    if _is_aiomax_null_raise(exc):
        logging.warning("%s no-op response %s (aiomax null raise)", label, ident)
        return
    if _is_aiomax_upload_failure(exc):
        logging.warning("%s upload returned no token %s", label, ident)
        return
    logging.exception("%s failed %s", label, ident)


async def safe_callback_answer(callback: aiomax.Callback, **kwargs):
    try:
        return await callback.answer(**kwargs)
    except Exception as exc:
        _log_aiomax_failure(
            "Max callback.answer",
            f"user={getattr(callback.user, 'user_id', '?')}",
            exc,
        )
        return None


async def safe_send_message(bot: aiomax.Bot, *args, **kwargs):
    chat_id = kwargs.get("chat_id") or kwargs.get("user_id") or (args[1] if len(args) > 1 else "?")
    try:
        return await bot.send_message(*args, **kwargs)
    except Exception as exc:
        _log_aiomax_failure("Max send_message", f"chat={chat_id}", exc)
        return None


_KEYBOARD_NOT_SET = object()


async def safe_edit_message(bot: aiomax.Bot, *args, keyboard=_KEYBOARD_NOT_SET, **kwargs):
    if keyboard is not _KEYBOARD_NOT_SET:
        kwargs["attachments"] = [_MaxKeyboardAttachment(keyboard)] if keyboard is not None else []
    try:
        return await bot.edit_message(*args, **kwargs)
    except Exception as exc:
        _log_aiomax_failure("Max edit_message", f"args={args[:1]}", exc)
        return None


async def safe_delete_message(bot: aiomax.Bot, message_id):
    try:
        return await bot.delete_message(str(message_id))
    except Exception as exc:
        _log_aiomax_failure("Max delete_message", f"msg={message_id}", exc)
        return None


async def safe_remove_keyboard(bot: aiomax.Bot, message_id):
    try:
        return await bot.edit_message(str(message_id), attachments=[])
    except Exception as exc:
        _log_aiomax_failure("Max remove_keyboard", f"msg={message_id}", exc)
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


def make_payment_actions_keyboard(order_id: str, payment_url: str) -> KeyboardBuilder:
    return (
        KeyboardBuilder()
        .row(LinkButton("💳 Оплатить", payment_url))
        .row(CallbackButton("Отменить платёж", f"payment:cancel:{order_id}"))
    )


def make_summarize_keyboard(
    transcription_id: int,
    show_summarize: bool = True,
    show_improve: bool = True,
    show_timecodes: bool = False,
) -> Optional[KeyboardBuilder]:
    buttons = []
    if show_summarize:
        buttons.append(CallbackButton("📝 Создать конспект", f"summarize:{transcription_id}"))
    if show_timecodes:
        buttons.append(CallbackButton("⏱ С таймкодами", f"tc:{transcription_id}"))
    if show_improve:
        buttons.append(CallbackButton("✏️ Знаки препинания и абзацы", f"improve:{transcription_id}"))
    if not buttons:
        return None
    kb = KeyboardBuilder()
    for btn in buttons:
        kb = kb.row(btn)
    return kb


def make_send_as_text_keyboard(
    transcription_id: int,
    show_send_as_text: bool = True,
    show_improve: bool = True,
    show_timecodes: bool = False,
) -> Optional[KeyboardBuilder]:
    buttons = []
    if show_send_as_text:
        buttons.append(CallbackButton("📄 Отправить текстом", f"send_as_text:{transcription_id}"))
    if show_timecodes:
        buttons.append(CallbackButton("⏱ С таймкодами", f"tc:{transcription_id}"))
    if show_improve:
        buttons.append(CallbackButton("✏️ Знаки препинания и абзацы", f"improve:{transcription_id}"))
    if not buttons:
        return None
    kb = KeyboardBuilder()
    for btn in buttons:
        kb = kb.row(btn)
    return kb


def make_timecodes_format_keyboard(transcription_id: int) -> KeyboardBuilder:
    return (
        KeyboardBuilder()
        .row(CallbackButton("📄 .txt с таймкодами", f"tc_fmt:{transcription_id}:txt"))
        .row(CallbackButton("🎬 .srt субтитры", f"tc_fmt:{transcription_id}:srt"))
        .row(CallbackButton("🎞 .vtt", f"tc_fmt:{transcription_id}:vtt"))
        .row(CallbackButton("← Назад", f"tc_back:{transcription_id}"))
    )


async def safe_send_document(bot: aiomax.Bot, chat_id, data, filename: str, caption: str, keyboard=None):
    try:
        file_attachment = await bot.upload_file(data, filename)
        attachments = []
        if keyboard is not None:
            attachments.append(_MaxKeyboardAttachment(keyboard))
        attachments.append(file_attachment)
        return await bot.send_message(caption, user_id=int(chat_id), attachments=attachments)
    except Exception as exc:
        _log_aiomax_failure("Max send_document", f"chat={chat_id} file={filename}", exc)
        return None
