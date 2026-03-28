"""Handler for /price command on Max messenger."""
import aiomax

from utils.sentry import sentry_bind_user_max


@sentry_bind_user_max
async def handle_max_price(message: aiomax.Message, bot: aiomax.Bot) -> None:
    await bot.send_message(
        "Стоимость распознавания:\n\n"
        "Провайдер: Yandex SpeechKit\n"
        "Цена: 0.15 ₽ за 15 секунд",
        chat_id=message.recipient.chat_id,
    )
