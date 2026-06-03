"""Characterization tests for is_owner ownership check."""
from types import SimpleNamespace

from database.models import PLATFORM_MAX, PLATFORM_TELEGRAM, is_owner


def _record(user_id, platform):
    return SimpleNamespace(user_id=user_id, user_platform=platform)


def test_owner_matches_user_and_platform():
    assert is_owner(_record(42, PLATFORM_TELEGRAM), 42, PLATFORM_TELEGRAM) is True


def test_none_record_is_not_owned():
    assert is_owner(None, 42, PLATFORM_TELEGRAM) is False


def test_different_user_is_not_owner():
    assert is_owner(_record(42, PLATFORM_TELEGRAM), 99, PLATFORM_TELEGRAM) is False


def test_same_user_different_platform_is_not_owner():
    assert is_owner(_record(42, PLATFORM_TELEGRAM), 42, PLATFORM_MAX) is False
