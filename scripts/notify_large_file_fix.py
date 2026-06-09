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

    python scripts/notify_large_file_fix.py          # dry run — just prints recipients
    python scripts/notify_large_file_fix.py --send    # actually deliver

Reads TELEGRAM_BOT_TOKEN and ADMIN_TELEGRAM_ID from .env. Before sending,
previews to the admin and asks for confirmation.
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import telegram

import messengers.telegram as tg_sender


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


PREVIEW_PREFIX = (
    "📋 PREVIEW рассылки.\n"
    "Это сообщение получат пользователи из списка. Текст ниже:\n\n"
)


async def send_telegram(token: str | None, user_ids: list[int], text: str) -> None:
    if not user_ids:
        return
    async with telegram.Bot(token=token) as bot:
        for uid in user_ids:
            res = await tg_sender.safe_send_message(bot, chat_id=uid, text=text)
            print(f"  telegram:{uid} -> {'ok' if res else 'FAILED/skipped'}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Notify affected Telegram users that large files are fixed")
    parser.add_argument("--send", action="store_true", help="actually send (default: dry run)")
    args = parser.parse_args()

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_admin = os.environ.get("ADMIN_TELEGRAM_ID")
    total = len(TELEGRAM_IDS)

    print(f"=== {'SEND' if args.send else 'DRY RUN'} — {total} recipients ===")
    print(f"Message:\n---\n{MESSAGE}\n---")

    if not args.send:
        for uid in TELEGRAM_IDS:
            print(f"  [dry-run] telegram:{uid}")
        print("\nDry run only. Re-run with --send to actually deliver.")
        return

    if not tg_token:
        print("TELEGRAM_BOT_TOKEN is not set")
        sys.exit(1)
    if not tg_admin:
        print("ADMIN_TELEGRAM_ID is not set (needed to preview to you)")
        sys.exit(1)

    # Preview to you BEFORE touching real users.
    preview = PREVIEW_PREFIX + MESSAGE
    print("\nSending preview to you...")
    await send_telegram(tg_token, [int(tg_admin)], preview)

    if input(f"\nType 'yes' to deliver to {total} users: ").strip() != "yes":
        print("Aborted.")
        return

    await send_telegram(tg_token, TELEGRAM_IDS, MESSAGE)


def _load_env() -> None:
    """Load .env if python-dotenv is available; otherwise rely on ambient env."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


if __name__ == "__main__":
    _load_env()
    asyncio.run(main())
