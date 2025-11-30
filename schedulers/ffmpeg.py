"""Periodic scheduler for updating ffmpeg preparation messages."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

from telegram.ext import ContextTypes

from utils.ffmpeg import get_conversion_progress
from utils.tg import safe_edit_message_text


BASE_MESSAGE = (
    "Файл получен\n\n"
    "Определяю длительность и стоимость перевода в текст\n"
    "Скоро попрошу подтвердить запуск задачи..."
)


@dataclass
class FFMpegStatus:
    """State for a single Telegram message with preparation progress."""

    chat_id: int
    message_id: int
    download_progress: int | None = None
    progress_file: Path | None = None
    duration_seconds: float | None = None
    conversion_started_at: float | None = None
    last_text: str | None = None

    def as_text(self) -> str:
        """Render current status text."""

        parts = [BASE_MESSAGE]

        if self.download_progress is not None:
            parts.append(f"\n\nСкачивание: {self.download_progress}%")

        conversion_progress = self.current_conversion_progress()
        if conversion_progress is not None:
            parts.append(f"\nКонвертация: {conversion_progress}%")

        return "".join(parts)

    def current_conversion_progress(self) -> int | None:
        if (
            self.progress_file is None
            or self.duration_seconds is None
            or self.conversion_started_at is None
        ):
            return None

        percent, _, _ = get_conversion_progress(
            self.progress_file, self.duration_seconds, self.conversion_started_at
        )
        return percent


def _storage(bot_data) -> Dict[Tuple[int, int], FFMpegStatus]:
    return bot_data.setdefault("ffmpeg_tasks", {})


def start_tracking(bot_data, chat_id: int, message_id: int) -> Tuple[int, int]:
    """Create a tracking entry and return its key."""

    key = (chat_id, message_id)
    _storage(bot_data)[key] = FFMpegStatus(chat_id=chat_id, message_id=message_id)
    return key


def update_download(bot_data, key: Tuple[int, int], percent: int) -> None:
    """Update download progress for the tracked message."""

    task = _storage(bot_data).get(key)
    if task:
        task.download_progress = max(0, min(100, percent))


def start_conversion(
    bot_data,
    key: Tuple[int, int],
    progress_file: Path,
    duration_seconds: float,
) -> None:
    """Mark that conversion has started for the tracked message."""

    task = _storage(bot_data).get(key)
    if task:
        task.progress_file = Path(progress_file)
        task.duration_seconds = duration_seconds
        task.conversion_started_at = time.time()


def stop_tracking(bot_data, key: Tuple[int, int]) -> None:
    """Remove tracking entry when work is finished."""

    _storage(bot_data).pop(key, None)


async def update_ffmpeg_messages(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodically update Telegram messages with download/conversion progress."""

    tasks = _storage(context.bot_data)
    for key, task in list(tasks.items()):
        text = task.as_text()
        if text == task.last_text:
            continue

        await safe_edit_message_text(
            context.bot,
            task.chat_id,
            task.message_id,
            text,
        )
        task.last_text = text
