"""Test configuration.

payment.py reads TERMINAL_KEY / TERMINAL_PASSWORD from the environment at
import time, and utils.utils transitively imports payment. Set dummy values
before any test module is collected so those imports succeed without real
credentials.
"""
import os

os.environ.setdefault("TERMINAL_KEY", "test-terminal-key")
os.environ.setdefault("TERMINAL_PASSWORD", "test-terminal-password")
