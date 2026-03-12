"""Utilities for counting LLM tokens."""
import tiktoken

from typing import Optional


ENCODING_NAMES = [
    "o200k_base",
    "cl100k_base",
]


def _count_tokens(text: str, encoding_name) -> Optional[int]:
    """Count tokens in *text* using tiktoken encoding *encoding_name*."""
    if not text:
        return 0
    try:
        encoding = tiktoken.get_encoding(encoding_name)
        return len(encoding.encode(text))
    except KeyError:
        return None


def tokens_by_model(text: str) -> dict[str, Optional[int]]:
    """Return token counts for *text* across supported models."""
    if not text:
        return {model: 0 for model in ENCODING_NAMES}
    return {
        encoding_name: _count_tokens(text, encoding_name)
        for encoding_name in ENCODING_NAMES
    }
