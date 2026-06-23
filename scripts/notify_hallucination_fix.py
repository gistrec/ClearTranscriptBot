#!/usr/bin/env python3
"""
Notify users whose good recording was wrongly refunded by the quality gate.

Root cause: ``looks_like_hallucination`` was too aggressive — a mean
``avg_logprob`` below -0.30 (genuine but hard audio runs to ~-0.41) and a single
phrase repeated 3x anywhere (which condemned even hour-long, high-confidence
transcripts). Real speech was rejected with the "no speech / too noisy" message
and refunded instead of delivered. Fixed in providers/replicate.py (threshold
-0.50, looping must dominate >=50% of segments) and locked by tests.

Recipients are read live from the DB: every distinct user with a transcription
in ``rejected`` status within SINCE_DAYS. That status only exists since the
quality-gate refund shipped, so the set is small and recent. The message is
deliberately conditional ("если вы с этим столкнулись"), so the few genuinely
unusable recordings in that set self-filter — no per-user good/garbage split,
and we never surface anyone's content.

Run only after the fix is deployed to prod.

    python scripts/notify_hallucination_fix.py          # dry run — lists recipients + previews to you
    python scripts/notify_hallucination_fix.py --send   # actually deliver

Send/preview/confirm logic and env handling live in broadcast.py.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from broadcast import cli
from database.connection import SessionLocal
from database.models import (
    Transcription,
    PLATFORM_TELEGRAM,
    PLATFORM_MAX,
    STATUS_REJECTED,
)


# ─────────────────────────── CONFIG — edit me ───────────────────────────
SINCE_DAYS = 30  # all current victims are from the last day; bound it anyway.

# Text delivered to every recipient.
MESSAGE = (
    "При недавнем обновлении была ошибка: проверка качества иногда принимала "
    "нормальную запись за неразборчивую и возвращала деньги вместо расшифровки. "
    "Уже исправили — больше такого не будет. Если вы с этим столкнулись, "
    "пришлите запись ещё раз — теперь всё распознается."
)
# ─────────────────────────────────────────────────────────────────────────


def rejected_user_ids(platform: str) -> list[int]:
    cutoff = datetime.now() - timedelta(days=SINCE_DAYS)
    with SessionLocal() as session:
        rows = (
            session.query(Transcription.user_id)
            .filter(
                Transcription.user_platform == platform,
                Transcription.status == STATUS_REJECTED,
                Transcription.created_at >= cutoff,
            )
            .distinct()
            .all()
        )
    return [row[0] for row in rows]


if __name__ == "__main__":
    cli(
        MESSAGE,
        telegram_ids=rejected_user_ids(PLATFORM_TELEGRAM),
        max_ids=rejected_user_ids(PLATFORM_MAX),
    )
