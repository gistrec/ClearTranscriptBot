#!/usr/bin/env python3
"""
Refund a user: add to their balance and send them a message.

Usage:
    python scripts/refund.py --platform telegram --user_id 12345 --amount 50 --message "Возврат за сбой"

Reads TELEGRAM_BOT_TOKEN / MAX_BOT_TOKEN from .env; the admin preview id is the
ADMIN_TELEGRAM_ID constant in broadcast.py.
"""
import argparse
import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import telegram
import aiomax

from broadcast import ADMIN_TELEGRAM_ID, _load_env
from database.models import PLATFORM_TELEGRAM, PLATFORM_MAX
from database.queries import get_user, change_user_balance


def parse_args():
    parser = argparse.ArgumentParser(description="Refund a user")
    parser.add_argument("--platform", required=True, choices=["telegram", "max"])
    parser.add_argument("--user_id", required=True, type=int)
    parser.add_argument("--amount", required=True, type=Decimal)
    parser.add_argument("--message", required=True)
    return parser.parse_args()


async def main():
    args = parse_args()
    _load_env()

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    max_token = os.environ.get("MAX_BOT_TOKEN")

    if not tg_token:
        print("TELEGRAM_BOT_TOKEN must be set")
        sys.exit(1)

    user = get_user(args.user_id, args.platform)
    if user is None:
        print(f"User {args.user_id} not found on {args.platform}")
        sys.exit(1)

    print(f"User:       {args.user_id} ({args.platform})")
    print(f"Balance:    {user.balance} ₽  →  {user.balance + args.amount} ₽  (+{args.amount})")
    print(f"Message:\n---\n{args.message}\n---\n")

    tg_bot = telegram.Bot(token=tg_token)
    preview = f"[PREVIEW — будет отправлено {args.platform}:{args.user_id}]\n\n{args.message}"
    await tg_bot.send_message(chat_id=ADMIN_TELEGRAM_ID, text=preview)

    print("Preview отправлен тебе в Telegram. Нажми Enter чтобы подтвердить, Ctrl+C для отмены.")
    try:
        input()
    except KeyboardInterrupt:
        print("\nОтменено.")
        sys.exit(0)

    if args.platform == PLATFORM_TELEGRAM:
        await tg_bot.send_message(chat_id=args.user_id, text=args.message)
    elif args.platform == PLATFORM_MAX:
        if not max_token:
            print("MAX_BOT_TOKEN не задан")
            sys.exit(1)
        max_bot = aiomax.Bot(access_token=max_token)
        await max_bot.send_message(args.message, user_id=args.user_id)

    updated = change_user_balance(args.user_id, args.platform, args.amount)
    print(f"Готово. Новый баланс: {updated.balance} ₽")


asyncio.run(main())
