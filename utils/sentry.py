import os
import logging
import functools
import sentry_sdk

from sentry_sdk.integrations.logging import LoggingIntegration


ENABLE_SENTRY = os.getenv("ENABLE_SENTRY") == "1"

if ENABLE_SENTRY:
    sentry_sdk.init(
        dsn=os.getenv("SENTRY_DSN"),
        enable_logs=True,
        send_default_pii=False,
        integrations=[LoggingIntegration(
            level=logging.INFO,
            event_level=logging.ERROR,
        )],
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
            sentry_sdk.set_user({
                "id": user.id,
                "username": user.username,
                "first_name": user.first_name,
            })
        return await func(update, context, *args, **kwargs)
    return wrapper
