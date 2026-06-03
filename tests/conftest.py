"""Test configuration.

Credentials are read lazily in config.py and validated only via
config.validate() at startup, so importing the modules under test needs no
real environment. This file intentionally has no setup.
"""
