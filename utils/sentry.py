import os
import logging
import functools
import sentry_sdk

from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
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
            HttpxIntegration(),
        ],
        disabled_integrations=[
            # FastAPI uses for healthcheck only
            FastApiIntegration(),
        ],
    )


def sentry_transaction(name, op="task"):
    """
    Async decorator that wraps a function in a Sentry transaction.
    No-op when ENABLE_SENTRY=0.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if not ENABLE_SENTRY:
                return await func(*args, **kwargs)

            with sentry_sdk.start_transaction(name=name, op=op):
                return await func(*args, **kwargs)

        return wrapper
    return decorator


def sentry_span(op, description=None):
    """
    Async decorator that creates a span within the current Sentry transaction.
    No-op when ENABLE_SENTRY=0.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if not ENABLE_SENTRY:
                return await func(*args, **kwargs)

            with sentry_sdk.start_span(op=op, description=description or func.__name__):
                return await func(*args, **kwargs)

        return wrapper
    return decorator


def sentry_drop_transaction() -> None:
    """
    Mark the current Sentry transaction as not sampled so it won't be sent.
    Call this to discard a transaction that isn't worth tracking (e.g. empty poll cycles).
    No-op when ENABLE_SENTRY=0 or no active transaction.
    """
    if not ENABLE_SENTRY:
        return

    transaction = sentry_sdk.get_current_scope().transaction
    if transaction is not None:
        transaction.sampled = False


def sentry_bind_user(func):
    """
    Async PTB handler decorator.
    If ENABLE_SENTRY=1 and update.effective_user exists -> set_user in Sentry.
    """
    @functools.wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        if ENABLE_SENTRY:
            user = getattr(update, "effective_user", None)

            user_id = getattr(user, "id", None)
            first_name = getattr(user, "first_name", None)

            if user_id is not None:
                with sentry_sdk.new_scope() as scope:
                    scope.set_user({
                        "id": user_id,
                        "first_name": first_name,
                    })
                    scope.set_tag("messenger", "telegram")

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
                    })
                    scope.set_tag("messenger", "max")

                    return await func(event, bot, *args, **kwargs)

        return await func(event, bot, *args, **kwargs)

    return wrapper
