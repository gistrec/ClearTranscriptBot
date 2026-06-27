#!/usr/bin/env python3
"""
Refund a user: add to their balance and send them a message.

Usage:
    python scripts/refund.py --platform telegram --user_id 12345 --amount 50 --message "Возврат за сбой"
    python scripts/refund.py --env .env.testing --platform telegram --user_id 12345 --amount 50 --message "..."
    python scripts/refund.py --platform telegram --user_id 12345 --amount 50 --message "..." --file result.txt

The --env file (default .env) supplies both the bot tokens and the MySQL
connection. With --file the message is sent as the document's caption, and the
preview shows the document too. The admin preview id is the ADMIN_TELEGRAM_ID
constant in broadcast.py.
"""
import argparse
import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _env_path_from_argv() -> str:
    """Read --env from argv before argparse runs.

    database.connection opens a pooled MySQL connection on import, so the env
    file must be loaded before the database import below — too early for main().
    """
    for i, arg in enumerate(sys.argv):
        if arg == "--env" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith("--env="):
            return arg.split("=", 1)[1]
    return ".env"


def _load_env(path: str) -> None:
    """Load the given env file if python-dotenv is available."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(path, override=True)


_load_env(_env_path_from_argv())

import telegram
import aiomax
from telegram import InputFile

import messengers.telegram as tg_sender
import messengers.max as max_sender
from broadcast import ADMIN_TELEGRAM_ID
from database.models import PLATFORM_TELEGRAM, PLATFORM_MAX
from database.queries import get_user, change_user_balance


def parse_args():
    parser = argparse.ArgumentParser(description="Refund a user")
    parser.add_argument("--env", default=".env", help="env file with tokens + MySQL creds (default: .env)")
    parser.add_argument("--platform", required=True, choices=["telegram", "max"])
    parser.add_argument("--user_id", required=True, type=int)
    parser.add_argument("--amount", required=True, type=Decimal)
    parser.add_argument("--message", required=True)
    parser.add_argument("--file", help="optional file to attach; message becomes its caption")
    return parser.parse_args()


async def main():
    args = parse_args()

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    max_token = os.environ.get("MAX_BOT_TOKEN")

    if not tg_token:
        print("TELEGRAM_BOT_TOKEN must be set")
        sys.exit(1)

    file_bytes = None
    file_name = None
    if args.file:
        file_path = Path(args.file)
        if not file_path.is_file():
            print(f"File not found: {args.file}")
            sys.exit(1)
        file_bytes = file_path.read_bytes()
        file_name = file_path.name

    user = get_user(args.user_id, args.platform)
    if user is None:
        print(f"User {args.user_id} not found on {args.platform}")
        sys.exit(1)

    print(f"User:       {args.user_id} ({args.platform})")
    print(f"Balance:    {user.balance} ₽  →  {user.balance + args.amount} ₽  (+{args.amount})")
    print(f"Attachment: {file_name or '—'}")
    print(f"Message:\n---\n{args.message}\n---\n")

    tg_bot = telegram.Bot(token=tg_token)
    preview = f"[PREVIEW — будет отправлено {args.platform}:{args.user_id}]\n\n{args.message}"
    if file_bytes is not None:
        await tg_sender.safe_send_document(
            tg_bot, ADMIN_TELEGRAM_ID, None,
            InputFile(file_bytes, filename=file_name), preview,
        )
    else:
        await tg_bot.send_message(chat_id=ADMIN_TELEGRAM_ID, text=preview)

    print("Preview отправлен тебе в Telegram. Нажми Enter чтобы подтвердить, Ctrl+C для отмены.")
    try:
        input()
    except KeyboardInterrupt:
        print("\nОтменено.")
        sys.exit(0)

    if args.platform == PLATFORM_TELEGRAM:
        if file_bytes is not None:
            await tg_sender.safe_send_document(
                tg_bot, args.user_id, None,
                InputFile(file_bytes, filename=file_name), args.message,
            )
        else:
            await tg_bot.send_message(chat_id=args.user_id, text=args.message)
    elif args.platform == PLATFORM_MAX:
        if not max_token:
            print("MAX_BOT_TOKEN не задан")
            sys.exit(1)
        max_bot = aiomax.Bot(access_token=max_token)
        if file_bytes is not None:
            await max_sender.safe_send_document(
                max_bot, args.user_id, file_bytes, file_name, args.message,
            )
        else:
            await max_bot.send_message(args.message, user_id=args.user_id)

    updated = change_user_balance(args.user_id, args.platform, args.amount)
    print(f"Готово. Новый баланс: {updated.balance} ₽")


asyncio.run(main())
