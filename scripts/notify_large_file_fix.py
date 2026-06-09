#!/usr/bin/env python3
"""
Notify Telegram users whose large file failed to download with a TimedOut.

Root cause (two parts):
1. In local Bot API mode the telegram-bot-api server downloads the whole file
   into /var/lib/telegram-bot-api before getFile returns. The YC VM had only
   ~3 GB free, so multi-GB files didn't fit — fixed by enlarging the disk.
2. get_file(read_timeout=120) blocks for that entire server-side download, and
   120 s was too short for big files → httpx.ReadTimeout → TimedOut (caught in
   handlers/telegram/file.py:handle_file), so the user got a misleading
   "не удалось загрузить, попробуйте ещё раз". Fixed by scaling the timeout with
   file size (handlers/telegram/file.py:_get_file_timeout).

Recipients below are the distinct Telegram users with a TimedOut in file.upload
(Sentry CLEAR-TRANSCRIPT-3N plus the same-cause group CLEAR-TRANSCRIPT-48). Two
of the eight users in 3N could not be recovered: their raw events aged out of
Sentry retention while only the tag counter survived.

    python scripts/notify_large_file_fix.py          # dry run — lists recipients + previews to you
    python scripts/notify_large_file_fix.py --send    # actually deliver

Send/preview/confirm logic and env handling live in broadcast.py.
"""
from broadcast import cli


# ─────────────────────────── CONFIG — edit me ───────────────────────────
# Distinct Telegram user-ids with a large-file TimedOut in file.upload.
# Trailing count = how many of their uploads timed out (repeats = retries).
TELEGRAM_IDS = [
    750824386,   # 3 timeouts (retries)
    1089535172,  # 1
    356138177,   # 1
    373259785,   # 1
    777837433,   # 1
    473524324,   # 1
    831539689,   # 1 (CLEAR-TRANSCRIPT-48)
]

# Text delivered to every recipient.
MESSAGE = (
    "Здравствуйте! 👋\n\n"
    "Недавно вы отправляли большой файл в наш бот, но он не загрузился "
    "из-за технического ограничения на размер. Приносим извинения 🙏\n\n"
    "Мы это исправили — теперь бот принимает длинные записи. Пришлите, "
    "пожалуйста, аудио или видео ещё раз, и мы вернём вам готовый текст 🎧"
)
# ─────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    cli(MESSAGE, telegram_ids=TELEGRAM_IDS)
