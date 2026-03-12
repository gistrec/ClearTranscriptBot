from datetime import timezone
from telegram import Update
from telegram.ext import ContextTypes

from database.queries import get_recent_transcriptions

from utils.sentry import sentry_bind_user
from utils.utils import format_duration, MoscowTimezone
from utils.tg import STATUS_EMOJI, fmt_price


@sentry_bind_user
async def handle_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    items = get_recent_transcriptions(telegram_id, limit=10)

    if not items:
        await update.message.reply_text(
            "История пуста\n\n"
            "Пришлите видео или аудио — вернём текст"
        )
        return


    lines: list[str] = []
    for r in items:
        emoji = STATUS_EMOJI.get(r.status, "•")
        dt = r.created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(MoscowTimezone)
        dt_str = dt.strftime("%Y-%m-%d %H:%M")
        dur = format_duration(r.duration_seconds)
        price_for_user = fmt_price(r.price_for_user)
        lines.append(f"{emoji} #{r.id} • {dt_str} МСК • {dur} • {price_for_user}")

    msg = (
        "Последние 10 распознаваний:\n"
        + "\n".join(lines)
        + "\n\nСтатусы: 🕓 ожидание • ⏳ в работе • ✅ готово • ❌ ошибка • 🚫 отменено"
    )

    await update.message.reply_text(msg)
