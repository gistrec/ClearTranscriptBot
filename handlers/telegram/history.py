from telegram import Update
from telegram.ext import ContextTypes

from database.models import PLATFORM_TELEGRAM
from database.queries import get_recent_transcriptions

from utils.sentry import sentry_bind_user, sentry_transaction
from utils.utils import format_duration, MoscowTimezone
from utils.tg import STATUS_EMOJI, fmt_price
from messengers.telegram import safe_reply_text


@sentry_bind_user
@sentry_transaction(name="history", op="telegram.command")
async def handle_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    items = get_recent_transcriptions(user_id, PLATFORM_TELEGRAM, limit=10)

    if not items:
        await safe_reply_text(
            update.message,
            "История пуста\n\n"
            "Пришлите видео или аудио — вернём текст"
        )
        return


    lines: list[str] = []
    for r in items:
        status = r.status if isinstance(r.status, str) else ""
        emoji = STATUS_EMOJI[status] if status in STATUS_EMOJI else "•"
        dt = r.created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=MoscowTimezone)
        dt_str = dt.strftime("%d.%m %H:%M")
        dur = format_duration(r.duration_seconds)
        price_for_user = fmt_price(r.price_for_user)
        lines.append(f"{emoji} {dt_str} МСК • {dur} • {price_for_user}")

    msg = (
        "Последние 10 распознаваний:\n"
        + "\n".join(lines)
        + "\n\nСтатусы: 🕓 ожидание • ⏳ в работе • ✅ готово • ❌ ошибка • 🚫 отменено"
    )

    await safe_reply_text(update.message, msg)
