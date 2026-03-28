"""File download utility for Max messenger attachments."""
import logging
from typing import Optional

import httpx


async def download_max_file(url: str) -> Optional[bytes]:
    """Download a Max file attachment by its direct URL."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    except Exception:
        logging.exception("Failed to download Max file from %s...", url[:80])
        return None
