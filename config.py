"""Centralized configuration for credentials validated at startup.

Reading happens lazily via os.getenv so importing this module (and anything
that depends on it, e.g. payment.py) never crashes when a variable is missing.
Call validate() once at startup to fail fast with a single clear message
listing everything that's missing.
"""
import os


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN")

TERMINAL_KEY = os.getenv("TERMINAL_KEY")
TERMINAL_PASSWORD = os.getenv("TERMINAL_PASSWORD")
TERMINAL_ENV = os.getenv("TERMINAL_ENV", "test")

# Required at runtime; MAX_BOT_TOKEN is optional (Max bot is opt-in).
_REQUIRED = ("TELEGRAM_BOT_TOKEN", "TERMINAL_KEY", "TERMINAL_PASSWORD")


def validate() -> None:
    """Raise if any required env var is unset. Call once at startup."""
    missing = [name for name in _REQUIRED if not globals()[name]]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )
