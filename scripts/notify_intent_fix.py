#!/usr/bin/env python3
"""
Notify Max users whose «Распознать» button silently failed on 2026-06-08.

Root cause: aiomax's CallbackButton.from_json read data["intent"], but Max omits
it, so every inline-button press raised KeyError('intent') before our handler ran
(fixed in commit 3a70178 / messengers/max.py patch_aiomax). Affected users sent a
file, pressed «Распознать», and nothing happened — their transcription is stuck
in status='pending'.

Recipients below are the distinct Max users with a PENDING transcription during
the bug window (2026-06-08 ~17:00–23:32 MSK). Excluded: three pre-bug abandoned
files (01:20 / 06:39 / 12:23 MSK, all with a delivered confirm message) and the
admin test account.

    python scripts/notify_intent_fix.py          # dry run — lists recipients + previews to admin
    python scripts/notify_intent_fix.py --send    # actually deliver

Reads MAX_BOT_TOKEN from .env. Before sending, previews to the admin and asks for
confirmation.
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp
import aiomax

import messengers.max as max_sender


# ─────────────────────────── CONFIG — edit me ───────────────────────────
# Distinct Max user-ids with a PENDING transcription in the bug window.
# Trailing count = how many of their files got stuck (rapid retries = the
# user pressing «Распознать» repeatedly and getting nothing back).
MAX_IDS = [
    23865714,   # 5 stuck files
    235700880,  # 4
    7434695,    # 3
    185585394,  # 2
    16686265,   # 2
    44856922,   # 2
    117850776,  # 1
    29117085,   # 1
    74997574,   # 1
    19244743,   # 1
    75044423,   # 1
    6176190,    # 1
    45552717,   # 1
]

# Text delivered to every recipient.
MESSAGE = (
    "Здравствуйте! 👋\n\n"
    "Вчера вы отправляли запись в наш бот, но кнопка «Распознать» не "
    "срабатывала из-за технической ошибки. Приносим извинения 🙏\n\n"
    "Сейчас всё исправлено. Пришлите, пожалуйста, аудио или видео ещё раз — "
    "и мы вернём вам готовый текст 🎧"
)

# Max user-id that receives the pre-send preview.
ADMIN_MAX_ID = 219203897
# ─────────────────────────────────────────────────────────────────────────


PREVIEW_PREFIX = (
    "📋 PREVIEW рассылки.\n"
    "Это сообщение получат пользователи из списка. Текст ниже:\n\n"
)


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
    parser = argparse.ArgumentParser(description="Notify affected Max users that the button is fixed")
    parser.add_argument("--send", action="store_true", help="actually send (default: dry run)")
    args = parser.parse_args()

    max_token = os.environ.get("MAX_BOT_TOKEN")
    total = len(MAX_IDS)

    print(f"=== {'SEND' if args.send else 'DRY RUN'} — {total} recipients ===")
    print(f"Message:\n---\n{MESSAGE}\n---")

    if not args.send:
        for uid in MAX_IDS:
            print(f"  [dry-run] max:{uid}")
        if max_token:
            max_sender.patch_aiomax()
            print("\nSending preview to admin (real users are NOT messaged)...")
            await send_max(max_token, [ADMIN_MAX_ID], PREVIEW_PREFIX + MESSAGE)
        else:
            print("\nSet MAX_BOT_TOKEN to also preview to the admin.")
        print("\nDry run only. Re-run with --send to actually deliver.")
        return

    if not max_token:
        print("MAX_BOT_TOKEN is not set")
        sys.exit(1)

    # Apply the same runtime patch the bot uses, so this script never trips over
    # the very bug it is announcing as fixed.
    max_sender.patch_aiomax()

    # Preview to the admin BEFORE touching real users.
    preview = PREVIEW_PREFIX + MESSAGE
    print("\nSending preview to admin...")
    await send_max(max_token, [ADMIN_MAX_ID], preview)

    if input(f"\nType 'yes' to deliver to {total} users: ").strip() != "yes":
        print("Aborted.")
        return

    await send_max(max_token, MAX_IDS, MESSAGE)


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
