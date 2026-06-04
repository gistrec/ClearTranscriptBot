#!/usr/bin/env python3
"""
One-off re-engagement broadcast.

Notifies users who complained that their transcription came out in the wrong
language (fixed by the WhisperX language-detection threshold change) that the
issue is resolved. These users were also credited a +36 ₽ bonus beforehand.

Dry run (default) — just prints who would receive the message:
    python scripts/broadcast_language_fix.py

Actually send:
    python scripts/broadcast_language_fix.py --send

Reads TELEGRAM_BOT_TOKEN / MAX_BOT_TOKEN from .env (or the environment).
For --send, also reads ADMIN_TELEGRAM_ID / ADMIN_MAX_ID and previews the
message to you on both platforms before the broadcast goes out.
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp
import telegram
import aiomax

import messengers.telegram as tg_sender
import messengers.max as max_sender
from database.models import PLATFORM_TELEGRAM, PLATFORM_MAX


# Users who left a wrong-language complaint and were credited +36 ₽.
TARGETS = [
    (PLATFORM_TELEGRAM, 2005560279),  # «Это английский а не русский»
    (PLATFORM_TELEGRAM, 7997412444),  # «Не на русском языке»
    (PLATFORM_TELEGRAM, 7933368418),  # «Какие то коды вместо текста»
    (PLATFORM_MAX, 48638886),         # «по французски … не то»
    (PLATFORM_MAX, 128595806),        # «Конспект как на украинском»
]

MESSAGE = (
    "Здравствуйте! Недавно вы распознавали аудио в нашем боте, "
    "но текст вышел не на том языке. Извините за это.\n\n"
    "Мы доработали автоопределение языка — теперь русская речь "
    "распознаётся корректно.\n\n"
    "В качестве извинения начислили вам бонус — его хватит примерно "
    "на час распознавания. Просто пришлите аудио или видео, и мы вернём текст 🎧"
)

PREVIEW_PREFIX = (
    "📋 PREVIEW рассылки про исправление языка.\n"
    "Это сообщение получат пользователи из списка. Текст ниже:\n\n"
)


async def send_telegram(token: str | None, user_ids: list[int], text: str) -> None:
    if not user_ids:
        return
    async with telegram.Bot(token=token) as bot:
        for uid in user_ids:
            res = await tg_sender.safe_send_message(bot, chat_id=uid, text=text)
            print(f"  telegram:{uid} -> {'ok' if res else 'FAILED/skipped'}")


async def send_max(token: str | None, user_ids: list[int], text: str) -> None:
    if not user_ids:
        return
    bot = aiomax.Bot(access_token=token)
    # send_message() requires an initialized session; start_polling() would set
    # one, but we only want to send, so build the same session manually.
    bot.session = aiohttp.ClientSession(headers={"Authorization": token})
    try:
        for uid in user_ids:
            res = await max_sender.safe_send_message(bot, text, user_id=uid)
            print(f"  max:{uid} -> {'ok' if res else 'FAILED/skipped'}")
    finally:
        await bot.session.close()
        bot.session = None


async def main() -> None:
    parser = argparse.ArgumentParser(description="Broadcast the language-fix apology")
    parser.add_argument("--send", action="store_true", help="actually send (default: dry run)")
    args = parser.parse_args()

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    max_token = os.environ.get("MAX_BOT_TOKEN")
    tg_admin = os.environ.get("ADMIN_TELEGRAM_ID")
    max_admin = os.environ.get("ADMIN_MAX_ID")

    tg_ids = [uid for p, uid in TARGETS if p == PLATFORM_TELEGRAM]
    max_ids = [uid for p, uid in TARGETS if p == PLATFORM_MAX]

    print(f"=== {'SEND' if args.send else 'DRY RUN'} — {len(TARGETS)} recipients ===")
    print(f"Message:\n---\n{MESSAGE}\n---")

    if not args.send:
        for uid in tg_ids:
            print(f"  [dry-run] telegram:{uid}")
        for uid in max_ids:
            print(f"  [dry-run] max:{uid}")
        print("\nDry run only. Re-run with --send to actually deliver.")
        return

    if tg_ids and not tg_token:
        print("TELEGRAM_BOT_TOKEN is not set")
        sys.exit(1)
    if max_ids and not max_token:
        print("MAX_BOT_TOKEN is not set")
        sys.exit(1)
    if tg_ids and not tg_admin:
        print("ADMIN_TELEGRAM_ID is not set (needed to preview to you)")
        sys.exit(1)
    if max_ids and not max_admin:
        print("ADMIN_MAX_ID is not set (needed to preview to you)")
        sys.exit(1)

    # Preview to you on both platforms BEFORE touching real users.
    preview = PREVIEW_PREFIX + MESSAGE
    print("\nSending preview to you...")
    if tg_ids:
        await send_telegram(tg_token, [int(tg_admin)], preview)
    if max_ids:
        await send_max(max_token, [int(max_admin)], preview)

    if input(f"\nType 'yes' to deliver to {len(TARGETS)} users: ").strip() != "yes":
        print("Aborted.")
        return

    await send_telegram(tg_token, tg_ids, MESSAGE)
    await send_max(max_token, max_ids, MESSAGE)


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
