"""Unified interface for transcription providers."""

from typing import Any, Dict, Optional

from providers import replicate as replicate_provider
from providers import speechkit as speechkit_provider
from utils.s3 import get_signed_url, object_name_from_url


async def start_transcription(
    audio_url: str,
    provider: str = "speechkit",
    language_code: str = "ru-RU",
) -> Optional[str]:
    """Start transcription and return the operation id."""

    if provider == "replicate":
        signed_url = await get_signed_url(object_name_from_url(audio_url))
        if not signed_url:
            return None
        return await replicate_provider.start_transcription(signed_url)

    return await speechkit_provider.start_transcription(audio_url, language_code)


async def check_transcription(operation_id: str, provider: str = "speechkit") -> Optional[Dict[str, Any]]:
    """Return transcription info if finished, otherwise ``None``."""

    if provider == "replicate":
        payload = await replicate_provider.check_transcription(operation_id)
    else:
        payload = await speechkit_provider.check_transcription(operation_id)

    if payload is None:
        return None

    if provider == "replicate":
        success = payload.get("status") == "succeeded" and bool(payload.get("output"))
    else:
        success = "response" in payload

    return {
        "provider": provider,
        "payload": payload,
        "success": success,
    }


def get_result(check_info: Dict[str, Any]) -> Optional[str]:
    """Extract transcription text from a finished check result."""

    if not check_info.get("success"):
        return None

    provider = check_info.get("provider")
    payload = check_info.get("payload") or {}

    if provider == "replicate":
        return replicate_provider.get_text(payload)
    else:
        return speechkit_provider.get_text(payload)
