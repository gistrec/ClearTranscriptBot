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

Send/preview/confirm logic and env handling live in broadcast.py (which also
applies patch_aiomax before any Max send).
"""
from broadcast import cli


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
# ─────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    cli(MESSAGE, max_ids=MAX_IDS)
