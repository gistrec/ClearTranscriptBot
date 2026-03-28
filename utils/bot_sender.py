"""Platform-agnostic message sender used by schedulers."""
import logging

from database.models import PLATFORM_TELEGRAM, PLATFORM_MAX


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
            try:
                await self._tg.edit_message_text(
                    chat_id=int(chat_id),
                    message_id=int(message_id),
                    text=text,
                    reply_markup=tg_markup,
                )
            except Exception:
                logging.exception(
                    "TG edit_message failed chat=%s msg=%s text=%r",
                    chat_id, message_id, text[:30],
                )
        elif platform == PLATFORM_MAX and self._max is not None:
            try:
                if max_keyboard is None:
                    await self._max.edit_message(str(message_id), text, attachments=[])
                else:
                    await self._max.edit_message(str(message_id), text, keyboard=max_keyboard)
            except Exception:
                logging.exception("Max edit_message failed msg=%s", message_id)

    async def send_message(
        self,
        platform: str,
        chat_id,
        text: str,
        tg_markup=None,
        max_keyboard=None,
    ):
        if platform == PLATFORM_TELEGRAM:
            return await self._tg.send_message(
                chat_id=int(chat_id),
                text=text,
                reply_markup=tg_markup,
            )
        elif platform == PLATFORM_MAX and self._max is not None:
            return await self._max.send_message(text, user_id=int(chat_id), keyboard=max_keyboard)

    async def remove_keyboard(self, platform: str, chat_id, message_id) -> None:
        """Remove inline keyboard from a message without changing its text."""
        if platform == PLATFORM_TELEGRAM:
            try:
                await self._tg.edit_message_reply_markup(
                    chat_id=int(chat_id),
                    message_id=int(message_id),
                    reply_markup=None,
                )
            except Exception:
                logging.exception(
                    "TG remove_keyboard failed chat=%s msg=%s", chat_id, message_id
                )
        elif platform == PLATFORM_MAX and self._max is not None:
            try:
                await self._max.edit_message(str(message_id), attachments=[])
            except Exception:
                logging.exception("Max remove_keyboard failed msg=%s", message_id)

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
            return await self._tg.send_document(
                chat_id=int(chat_id),
                reply_to_message_id=int(reply_to_message_id),
                document=file_obj,
                caption=caption,
                reply_markup=tg_markup,
                **tg_kwargs,
            )
        elif platform == PLATFORM_MAX and self._max is not None:
            data = file_obj.read() if hasattr(file_obj, "read") else file_obj
            try:
                file_attachment = await self._max.upload_file(data, filename)
                return await self._max.send_message(
                    caption,
                    user_id=int(chat_id),
                    attachments=[file_attachment],
                    keyboard=max_keyboard,
                )
            except Exception:
                logging.exception("Max send_document failed chat=%s", chat_id)
