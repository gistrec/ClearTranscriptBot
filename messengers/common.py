"""Platform-agnostic message sender used by schedulers."""
from database.models import PLATFORM_TELEGRAM, PLATFORM_MAX
import messengers.max as max_sender
import messengers.telegram as tg_sender


class BotSender:
    """Routes message delivery to the correct bot based on platform."""

    def __init__(self, tg_bot, max_bot):
        self._tg = tg_bot
        self._max = max_bot

    async def edit_message(
        self,
        platform: str,
        chat_id,
        message_id,
        text: str,
        tg_markup=None,
        max_keyboard=None,
    ) -> None:
        if platform == PLATFORM_TELEGRAM:
            await tg_sender.safe_edit_message(self._tg, chat_id, message_id, text, tg_markup)
        elif platform == PLATFORM_MAX and self._max is not None:
            if max_keyboard is None:
                await max_sender.safe_edit_message(self._max, str(message_id), text, attachments=[])
            else:
                await max_sender.safe_edit_message(self._max, str(message_id), text, keyboard=max_keyboard)

    async def send_message(
        self,
        platform: str,
        chat_id,
        text: str,
        tg_markup=None,
        max_keyboard=None,
    ):
        if platform == PLATFORM_TELEGRAM:
            return await tg_sender.safe_send_message(
                self._tg, chat_id=int(chat_id), text=text, reply_markup=tg_markup
            )
        elif platform == PLATFORM_MAX and self._max is not None:
            return await max_sender.safe_send_message(
                self._max, text, user_id=int(chat_id), keyboard=max_keyboard
            )

    async def remove_keyboard(self, platform: str, chat_id, message_id) -> None:
        if platform == PLATFORM_TELEGRAM:
            await tg_sender.safe_remove_keyboard(self._tg, chat_id, message_id)
        elif platform == PLATFORM_MAX and self._max is not None:
            await max_sender.safe_remove_keyboard(self._max, message_id)

    async def send_document(
        self,
        platform: str,
        chat_id,
        reply_to_message_id,
        file_obj,
        filename: str,
        caption: str,
        tg_markup=None,
        max_keyboard=None,
        **tg_kwargs,
    ):
        if platform == PLATFORM_TELEGRAM:
            return await tg_sender.safe_send_document(
                self._tg, chat_id, reply_to_message_id, file_obj, caption, tg_markup, **tg_kwargs
            )
        elif platform == PLATFORM_MAX and self._max is not None:
            data = file_obj.read() if hasattr(file_obj, "read") else file_obj
            return await max_sender.safe_send_document(
                self._max, chat_id, data, filename, caption, max_keyboard
            )
