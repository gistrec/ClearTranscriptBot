"""Periodic scheduler for checking transcription statuses."""
from __future__ import annotations

from pathlib import Path

from telegram.ext import ContextTypes

from database.queries import get_transcriptions_by_status, update_transcription
from utils.speechkit import get_transcription


async def check_running_tasks(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Poll running transcriptions and send results when ready."""
    bot = context.bot
    tasks = get_transcriptions_by_status("running")
    for item in tasks:
        result = get_transcription(item.operation_id)
        if result is None:
            continue
        text = "\n".join(c.get("text", "") for c in result.get("chunks", []))
        path = Path(f"transcription_{item.id}.txt")
        path.write_text(text, encoding="utf-8")
        try:
            await bot.send_document(chat_id=item.telegram_id, document=path.open("rb"))
        finally:
            path.unlink(missing_ok=True)
        update_transcription(item.id, status="completed", result_s3_path=None)
