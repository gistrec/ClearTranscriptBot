"""Liveness probe for the Telegram and Max polling loops.

The job-queue beats (transcription/refinement/payments) already prove the event
loop and job queue are alive, but say nothing about whether each bot is still
talking to its platform API. Both PTB and aiomax retry getUpdates forever on
failure, so a revoked token or a platform outage leaves the process looping
silently while no updates reach users. This actively calls get_me() on every
enabled bot each tick and beats only when all succeed, turning that silent
stall into a healthcheck 503.

A single "pollers" beat (not one per bot) is enough: both bots share one
process, so any restart triggered by the 503 brings both back regardless. The
warning logs below name which bot actually failed.
"""
import logging

import utils.heartbeat as heartbeat

from telegram.ext import ContextTypes


async def check_pollers(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Probe each enabled poller; beat only if all are reachable."""
    healthy = True

    if context.application.updater.running:
        try:
            await context.bot.get_me()
        except Exception:
            logging.warning("Poller check: Telegram get_me failed", exc_info=True)
            healthy = False
    else:
        healthy = False

    max_bot = context.bot_data.get("max_bot")
    if max_bot is not None:
        if getattr(max_bot, "polling", False):
            try:
                await max_bot.get_me()
            except Exception:
                logging.warning("Poller check: Max get_me failed", exc_info=True)
                healthy = False
        else:
            healthy = False

    if healthy:
        heartbeat.beat("pollers")
