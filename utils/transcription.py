"""Unified interface for transcription providers."""

from typing import Any, Dict, Optional, Tuple

from providers import replicate as replicate_provider
from providers import speechkit as speechkit_provider
from utils.s3 import get_signed_url, object_name_from_url


def _split_operation_id(operation_id: str, default_provider: str = "speechkit") -> Tuple[str, str]:
    if ":" not in operation_id:
        return default_provider, operation_id
    provider, op_id = operation_id.split(":", 1)
    return provider, op_id


async def start_transcription(
    audio_url: str,
    provider: str = "speechkit",
    duration_seconds: Optional[int] = None,
    language_code: str = "ru-RU",
) -> Optional[str]:
    """Start transcription and return a provider-aware operation id."""

    if provider == "replicate":
        signed_url = await get_signed_url(object_name_from_url(audio_url))
        if not signed_url:
            return None
        op_id = await replicate_provider.start_transcription(signed_url)
        return f"replicate:{op_id}" if op_id else None

    op_id = await speechkit_provider.run_transcription(audio_url, language_code)
    return f"speechkit:{op_id}" if op_id else None


async def check_transcription(operation_id: str) -> Optional[Dict[str, Any]]:
    """Return transcription info if finished, otherwise ``None``."""

    provider, op_id = _split_operation_id(operation_id)

    if provider == "replicate":
        payload = await replicate_provider.check_transcription(op_id)
    else:
        payload = await speechkit_provider.fetch_transcription_result(op_id)

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
    return speechkit_provider.parse_text(payload)
