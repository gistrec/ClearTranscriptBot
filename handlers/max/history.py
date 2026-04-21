"""Handler for /history command on Max messenger."""
import logging

import aiomax

from database.models import PLATFORM_MAX
from database.queries import get_recent_transcriptions
from utils.utils import format_duration, MoscowTimezone
from utils.tg import STATUS_EMOJI, fmt_price
from utils.sentry import sentry_bind_user_max, sentry_transaction
from messengers.max import safe_send_message


@sentry_bind_user_max
@sentry_transaction(name="history", op="max.command")
async def handle_max_history(message: aiomax.Message, bot: aiomax.Bot) -> None:
    try:
        user_id = int(message.sender.user_id)
    except (ValueError, TypeError):
        logging.error("Max: cannot parse user_id: %s", message.sender)
        return

    items = get_recent_transcriptions(user_id, PLATFORM_MAX, limit=10)

    if not items:
        await safe_send_message(bot, 
            "История пуста\n\n"
            "Пришлите видео или аудио — вернём текст",
            chat_id=message.recipient.chat_id,
        )
        return

    lines: list[str] = []
    for r in items:
        emoji = STATUS_EMOJI.get(r.status, "•")
        dt = r.created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=MoscowTimezone)
        dt_str = dt.strftime("%d.%m %H:%M")
        dur = format_duration(r.duration_seconds)
        price_for_user = fmt_price(r.price_for_user)
        lines.append(f"{emoji} #{r.id} • {dt_str} МСК • {dur} • {price_for_user}")

    msg = (
        "Последние 10 распознаваний:\n"
        + "\n".join(lines)
        + "\n\nСтатусы: 🕓 ожидание • ⏳ в работе • ✅ готово • ❌ ошибка • 🚫 отменено"
    )

    await safe_send_message(bot, msg, chat_id=message.recipient.chat_id)
