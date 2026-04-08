import os
import logging
import functools
import sentry_sdk

from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration


ENABLE_SENTRY = os.getenv("ENABLE_SENTRY") == "1"

if ENABLE_SENTRY:
    sentry_sdk.init(
        dsn=os.getenv("SENTRY_DSN"),
        enable_logs=True,
        send_default_pii=False,
        traces_sample_rate=1.0,
        integrations=[
            LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR,
            ),
            SqlalchemyIntegration(),
        ],
    )


def sentry_bind_user(func):
    """
    Async PTB handler decorator.
    If ENABLE_SENTRY=1 and update.effective_user exists -> set_user in Sentry.
    """
    @functools.wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        if ENABLE_SENTRY and getattr(update, "effective_user", None):
            user = update.effective_user

            with sentry_sdk.new_scope() as scope:
                scope.set_user({
                    "id": user.id,
                    "first_name": user.first_name,
                    "platform": "telegram",
                })

                return await func(update, context, *args, **kwargs)

        return await func(update, context, *args, **kwargs)

    return wrapper


def sentry_bind_user_max(func):
    """
    Async Max handler decorator (aiomax.Message or aiomax.Callback as first arg).
    If ENABLE_SENTRY=1 -> set_user in Sentry from sender.user_id / user.user_id.
    """
    @functools.wraps(func)
    async def wrapper(event, bot, *args, **kwargs):
        if ENABLE_SENTRY:
            # aiomax.Message uses .sender; aiomax.Callback uses .user
            user = getattr(event, "sender", None) or getattr(event, "user", None)

            user_id = getattr(user, "user_id", None)
            name = getattr(user, "name", None)

            if user_id is not None:
                with sentry_sdk.new_scope() as scope:
                    scope.set_user({
                        "id": user_id,
                        "first_name": name,
                        "platform": "max",
                    })

                    return await func(event, bot, *args, **kwargs)

        return await func(event, bot, *args, **kwargs)

    return wrapper
