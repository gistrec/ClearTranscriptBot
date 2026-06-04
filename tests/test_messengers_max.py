"""Characterization tests for Max recipient-unreachable classification."""
from aiomax.exceptions import ChatNotFound, UnknownErrorException

from messengers.max import _is_dialog_unavailable


def test_chat_not_found_is_unavailable():
    assert _is_dialog_unavailable(ChatNotFound("Chat with user 1 not found")) is True


def test_dialog_not_found_is_unavailable():
    exc = UnknownErrorException("dialog.not.found", "error.dialog.notfound")
    assert _is_dialog_unavailable(exc) is True


def test_chat_denied_is_unavailable():
    exc = UnknownErrorException("chat.denied", "error.chat.denied")
    assert _is_dialog_unavailable(exc) is True


def test_unrelated_error_is_not_unavailable():
    assert _is_dialog_unavailable(ValueError("boom")) is False
