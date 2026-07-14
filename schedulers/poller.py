"""Liveness probe for the Telegram and Max polling loops.

The job-queue beats (transcription/refinement/payments) already prove the event
loop and job queue are alive, but say nothing about whether each bot is still
talking to its platform API. Both PTB and aiomax retry getUpdates forever on
failure, so a revoked token or a platform outage leaves the process looping
silently while no updates reach users. This actively calls get_me() on every
enabled bot each tick and beats only when all succeed, turning that silent
stall into a healthcheck 503.

get_me() is NOT a sufficient Telegram probe here: the bot talks to a local
Bot API server, which answers getMe from its own cache even after losing its
upstream link to Telegram (the 2026-07-14 outage: nftables cut the server off
from Telegram DCs while every local check kept passing). When
ADMIN_TELEGRAM_ID is set, the probe instead sends a typing chat action to the
admin chat — that request must cross bot -> local server -> Telegram, so it
fails within the read timeout whenever any hop is dead. get_me remains the
fallback for setups without an admin chat configured.

A single "pollers" beat (not one per bot) is enough: both bots share one
process, so any restart triggered by the 503 brings both back regardless. The
warning logs below name which bot actually failed.
"""
import logging

import config
import utils.heartbeat as heartbeat

from telegram.constants import ChatAction
from telegram.ext import ContextTypes


async def check_pollers(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Probe each enabled poller; beat only if all are reachable."""
    healthy = True

    if context.application.updater.running:
        try:
            if config.ADMIN_TELEGRAM_ID:
                await context.bot.send_chat_action(
                    config.ADMIN_TELEGRAM_ID, ChatAction.TYPING
                )
            else:
                await context.bot.get_me()
        except Exception:
            logging.warning("Poller check: Telegram probe failed", exc_info=True)
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
