"""Handler for /price command on Max messenger."""
import aiomax

from utils.sentry import sentry_bind_user_max, sentry_transaction
from messengers.max import safe_send_message


@sentry_bind_user_max
@sentry_transaction(name="price", op="max.command")
async def handle_max_price(message: aiomax.Message, bot: aiomax.Bot) -> None:
    await safe_send_message(bot,
        "Стоимость распознавания:\n\n"
        "Провайдер: Yandex SpeechKit\n"
        "Цена: 0.15 ₽ за 15 секунд",
        chat_id=message.recipient.chat_id,
    )
