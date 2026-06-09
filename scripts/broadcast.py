#!/usr/bin/env python3
"""
Broadcast a message to a hand-picked list of Telegram + Max users.

Edit the recipient ids and the message in the CONFIG block below, then:

    python scripts/broadcast.py            # dry run — lists recipients + previews to you
    python scripts/broadcast.py --send     # actually deliver

Reads TELEGRAM_BOT_TOKEN / MAX_BOT_TOKEN (and ADMIN_TELEGRAM_ID for the
Telegram self-preview) from .env. Before sending, previews the message to
you and asks for confirmation.
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


# ─────────────────────────── CONFIG — edit me ───────────────────────────
# Recipient user-ids per platform.
TELEGRAM_IDS = [
    2005560279,  # «Это английский а не русский»
    7997412444,  # «Не на русском языке»
    7933368418,  # «Какие то коды вместо текста»
]

MAX_IDS = [
    48638886,    # «по французски … не то»
    128595806,   # «Конспект как на украинском»
]

# Text delivered to every recipient.
MESSAGE = (
    "Здравствуйте! Недавно вы распознавали аудио в нашем боте, "
    "но текст вышел не на том языке. Извините за это.\n\n"
    "Мы доработали автоопределение языка — теперь русская речь "
    "распознаётся корректно.\n\n"
    "В качестве извинения начислили вам бонус — его хватит примерно "
    "на час распознавания. Просто пришлите аудио или видео, и мы вернём текст 🎧"
)

# Max user-id that receives the pre-send preview.
ADMIN_MAX_ID = 219203897
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
    parser = argparse.ArgumentParser(description="Broadcast a message to a fixed list of users")
    parser.add_argument("--send", action="store_true", help="actually send (default: dry run)")
    args = parser.parse_args()

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    max_token = os.environ.get("MAX_BOT_TOKEN")
    tg_admin = os.environ.get("ADMIN_TELEGRAM_ID")

    tg_ids = TELEGRAM_IDS
    max_ids = MAX_IDS
    total = len(tg_ids) + len(max_ids)

    print(f"=== {'SEND' if args.send else 'DRY RUN'} — {total} recipients ===")
    print(f"Message:\n---\n{MESSAGE}\n---")

    if not args.send:
        for uid in tg_ids:
            print(f"  [dry-run] telegram:{uid}")
        for uid in max_ids:
            print(f"  [dry-run] max:{uid}")
        preview = PREVIEW_PREFIX + MESSAGE
        print("\nPreview to you (real users are NOT messaged):")
        if tg_ids and tg_token and tg_admin:
            await send_telegram(tg_token, [int(tg_admin)], preview)
        if max_ids and max_token:
            await send_max(max_token, [ADMIN_MAX_ID], preview)
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

    # Preview to you on both platforms BEFORE touching real users.
    preview = PREVIEW_PREFIX + MESSAGE
    print("\nSending preview to you...")
    if tg_ids:
        await send_telegram(tg_token, [int(tg_admin)], preview)
    if max_ids:
        await send_max(max_token, [ADMIN_MAX_ID], preview)

    if input(f"\nType 'yes' to deliver to {total} users: ").strip() != "yes":
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
