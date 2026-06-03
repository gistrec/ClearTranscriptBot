"""Handler for /price command on Max messenger."""
import aiomax

from utils.sentry import sentry_bind_user_max, sentry_transaction
from messengers.max import safe_send_message


@sentry_bind_user_max
@sentry_transaction(name="price", op="max.command")
async def handle_max_price(message: aiomax.Message, bot: aiomax.Bot) -> None:
    await safe_send_message(bot,
        "Стоимость распознавания речи:\n\n"
        "Цена: 0,01 ₽ за 1 секунду аудио, например:\n\n"
        "• 0,60 ₽ за минуту\n"
        "• 36 ₽ за час\n\n"
        "Минимальная стоимость одной записи — 1 ₽",
        chat_id=message.recipient.chat_id,
    )
