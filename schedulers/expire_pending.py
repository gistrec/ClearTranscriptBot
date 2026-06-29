"""Periodic scheduler that silently expires abandoned pending transcriptions.

A pending transcription is an uploaded file awaiting the user's 'Распознать'
click. Almost all confirmations happen within minutes; anything still pending
after a week is abandoned. The source audio in S3 is also lifecycle-deleted at
~30 days, so an old pending row points at a file that will soon vanish.

The job only flips the status in the DB — no message is sent and the original
keyboard is left untouched. A later click on the stale button hits the same
not_pending path as a cancelled task, so the user is never charged.
"""
import logging

from datetime import datetime, timedelta

from telegram.ext import ContextTypes

from database.queries import expire_stale_pending_transcriptions
from utils.utils import MoscowTimezone
from utils.sentry import sentry_transaction, sentry_drop_transaction


_EXPIRE_AFTER_DAYS = 7


@sentry_transaction(name="transcription.expire_pending", op="task.expire")
async def expire_stale_pending(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Move pending transcriptions older than a week to the expired status."""
    cutoff = datetime.now(MoscowTimezone) - timedelta(days=_EXPIRE_AFTER_DAYS)
    try:
        expired = expire_stale_pending_transcriptions(cutoff)
    except Exception:
        logging.exception("Failed to expire stale pending transcriptions")
        sentry_drop_transaction()
        return

    if expired:
        logging.info("Expired %d stale pending transcriptions", expired)
    else:
        sentry_drop_transaction()
