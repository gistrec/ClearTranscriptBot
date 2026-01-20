"""Utilities for counting LLM tokens."""
import tiktoken

from typing import Optional


LLM_TOKEN_MODELS = [
    "gpt-5.2",
    "gpt-5.1",
    "gpt-5-mini",
    "gpt-5-nano",
]

DEFAULT_ENCODING = "o200k_base"


def count_tokens(text: str, model: str = LLM_TOKEN_MODELS[0]) -> Optional[int]:
    """Count tokens in *text* using tiktoken encoding for *model*."""
    try:
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except KeyError:
        return None


def tokens_by_model(text: str) -> dict[str, Optional[int]]:
    """Return token counts for *text* across supported models."""
    if not text.strip():
        return {model: 0 for model in LLM_TOKEN_MODELS}
    return {
        model: count_tokens(text, model=model)
        for model in LLM_TOKEN_MODELS
    }
