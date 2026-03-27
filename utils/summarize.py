"""Replicate LLM wrapper for transcription summarization."""
import asyncio
import logging
import os
import replicate

from typing import Optional


REPLICATE_LLM_MODEL = "openai/gpt-5-mini"

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

SUMMARIZE_PROMPT = (
    "Ты — помощник, который создаёт краткие конспекты текстов.\n\n"
    "Создай структурированный конспект следующей транскрипции аудио. "
    "Выдели ключевые темы, основные тезисы и важные детали. "
    "Отвечай на том же языке, что и исходный текст.\n\n"
    "Транскрипция:\n{text}"
)


async def start_summarization(text: str) -> Optional[str]:
    """Submit a summarization prediction to Replicate.

    Returns the prediction ID on success, or None on failure.
    """
    prompt = SUMMARIZE_PROMPT.format(text=text)

    def _create() -> Optional[str]:
        try:
            client = replicate.Client(api_token=REPLICATE_API_TOKEN)
            prediction = client.predictions.create(
                model=REPLICATE_LLM_MODEL,
                input={"prompt": prompt},
            )
            return prediction.id
        except Exception:
            logging.exception("Failed to start summarization on Replicate")
            return None

    return await asyncio.to_thread(_create)


async def check_summarization(operation_id: str) -> Optional[dict]:
    """Poll a Replicate prediction.

    Returns ``{"success": bool, "text": str}`` when finished,
    or ``None`` if the prediction is still running.
    """
    def _check() -> Optional[dict]:
        try:
            client = replicate.Client(api_token=REPLICATE_API_TOKEN)
            prediction = client.predictions.get(operation_id)
        except Exception:
            logging.exception(f"Failed to fetch summarization prediction {operation_id}")
            return {"success": False, "text": ""}

        if prediction.status not in {"succeeded", "failed", "canceled"}:
            return None

        if prediction.status != "succeeded":
            return {"success": False, "text": ""}

        output = prediction.output
        if isinstance(output, list):
            text = "".join(output)
        elif isinstance(output, str):
            text = output
        else:
            text = ""

        return {"success": True, "text": text.strip()}

    return await asyncio.to_thread(_check)
