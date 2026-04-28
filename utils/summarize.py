"""Replicate LLM wrapper for transcription summarization."""
import asyncio
import logging
import os
import replicate

from typing import Optional

from utils.sentry import sentry_span


REPLICATE_LLM_MODEL = "openai/gpt-5-mini"

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

client = replicate.Client(api_token=REPLICATE_API_TOKEN)

SUMMARIZE_PROMPT = (
    "Ты — помощник, который делает очень короткие, точные и удобные для чтения конспекты транскрипций аудио.\n\n"

    "Твоя задача:\n"
    "- выделить главную мысль\n"
    "- оставить только самое важное\n"
    "- убрать повторы, междометия, слова-паразиты и лишнюю разговорную часть\n"
    "- ничего не придумывать от себя\n\n"

    "Правила:\n"
    "- Отвечай на том же языке, что и исходный текст.\n"
    "- Не добавляй факты, которых нет в транскрипции.\n"
    "- Если часть текста неясна, не додумывай её.\n"
    "- Сохраняй важные цифры, суммы, сроки, имена, названия и выводы, если они есть.\n"
    "- Если в тексте мало полезного содержания, честно скажи об этом коротко.\n"
    "- Не переписывай текст целиком.\n"
    "- Пиши просто, ясно и без воды.\n\n"

    "Сформируй ответ СТРОГО в формате:\n\n"

    "Вывод:\n"
    "<одно короткое предложение, максимум 140 символов>\n\n"

    "Кратко:\n"
    "• <короткий тезис 1>\n"
    "• <короткий тезис 2>\n"
    "• <короткий тезис 3>\n"
    "• <короткий тезис 4, если нужен>\n\n"

    "Ограничения:\n"
    "- В блоке 'Кратко' должно быть 3-4 пункта.\n"
    "- Каждый пункт — одна самостоятельная мысль.\n"
    "- Каждый пункт должен быть коротким, без длинных пояснений.\n"
    "- Сначала пиши результат, решение или главный вывод, если он есть.\n"
    "- Не используй раздел 'Подробно'.\n"
    "- Не используй вступления, дисклеймеры и фразы вроде 'Вот краткий конспект'.\n\n"

    "Транскрипция:\n{text}"
)


@sentry_span(op="refinement.start")
async def start_refinement(text: str) -> Optional[str]:
    """Submit a summarization prediction to Replicate.

    Returns the prediction ID on success, or None on failure.
    """
    prompt = SUMMARIZE_PROMPT.format(text=text)

    def _create() -> Optional[str]:
        try:
            prediction = client.predictions.create(
                model=REPLICATE_LLM_MODEL,
                input={"prompt": prompt},
            )
            return prediction.id
        except Exception:
            logging.exception("Failed to start summarization on Replicate")
            return None

    return await asyncio.to_thread(_create)


@sentry_span(op="refinement.check")
async def check_refinement(operation_id: str) -> Optional[dict]:
    """Poll a Replicate prediction.

    Returns ``{"success": bool, "text": str}`` when finished,
    or ``None`` if the prediction is still running.
    """
    def _check() -> Optional[dict]:
        try:
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
