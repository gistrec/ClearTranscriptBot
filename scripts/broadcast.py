#!/usr/bin/env python3
"""
Broadcast a message to a hand-picked list of Telegram + Max users.

Edit the recipient ids and the message in the CONFIG block below, then:

    python scripts/broadcast.py            # dry run — lists recipients + previews to you
    python scripts/broadcast.py --send     # actually deliver

Reads TELEGRAM_BOT_TOKEN / MAX_BOT_TOKEN from .env; the admin preview ids are
constants in the CONFIG block. Before sending, previews the message to you and
asks for confirmation.

cli() also backs the thin notify_*.py scripts: they import it and supply only
their own recipient ids + message text.
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

# Admin user-ids that receive the pre-send (and dry-run) preview.
ADMIN_TELEGRAM_ID = 394190148
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


async def _run(message: str, telegram_ids: list[int], max_ids: list[int], *, send: bool) -> None:
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    max_token = os.environ.get("MAX_BOT_TOKEN")
    total = len(telegram_ids) + len(max_ids)

    if max_ids:
        # Same runtime patch the bot uses, so a Max send never trips the aiomax
        # intent bug this tooling exists to work around.
        max_sender.patch_aiomax()

    print(f"=== {'SEND' if send else 'DRY RUN'} — {total} recipients ===")
    print(f"Message:\n---\n{message}\n---")
    prefix = "" if send else "[dry-run] "
    for uid in telegram_ids:
        print(f"  {prefix}telegram:{uid}")
    for uid in max_ids:
        print(f"  {prefix}max:{uid}")

    preview = PREVIEW_PREFIX + message

    if not send:
        print("\nPreview to you (real users are NOT messaged):")
        if telegram_ids and tg_token:
            await send_telegram(tg_token, [ADMIN_TELEGRAM_ID], preview)
        if max_ids and max_token:
            await send_max(max_token, [ADMIN_MAX_ID], preview)
        print("\nDry run only. Re-run with --send to actually deliver.")
        return

    if telegram_ids and not tg_token:
        print("TELEGRAM_BOT_TOKEN is not set")
        sys.exit(1)
    if max_ids and not max_token:
        print("MAX_BOT_TOKEN is not set")
        sys.exit(1)

    # Preview to you BEFORE touching real users.
    print("\nSending preview to you...")
    if telegram_ids:
        await send_telegram(tg_token, [ADMIN_TELEGRAM_ID], preview)
    if max_ids:
        await send_max(max_token, [ADMIN_MAX_ID], preview)

    if input(f"\nType 'yes' to deliver to {total} users: ").strip() != "yes":
        print("Aborted.")
        return

    await send_telegram(tg_token, telegram_ids, message)
    await send_max(max_token, max_ids, message)


def _load_env() -> None:
    """Load .env if python-dotenv is available; otherwise rely on ambient env."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def cli(message: str, *, telegram_ids: list[int] | None = None, max_ids: list[int] | None = None) -> None:
    """Entry point for broadcast scripts: parse --send, load .env, then
    dry-run/preview/confirm/deliver. Callers supply only the text and ids."""
    parser = argparse.ArgumentParser(description="Broadcast a message to a fixed list of users")
    parser.add_argument("--send", action="store_true", help="actually send (default: dry run)")
    args = parser.parse_args()

    _load_env()
    asyncio.run(_run(message, telegram_ids or [], max_ids or [], send=args.send))


if __name__ == "__main__":
    cli(MESSAGE, telegram_ids=TELEGRAM_IDS, max_ids=MAX_IDS)
