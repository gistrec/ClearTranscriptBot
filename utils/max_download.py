"""File download utility for Max messenger attachments."""
import logging
from pathlib import Path

import httpx


async def download_max_file(url: str, destination: str | Path) -> bool:
    """Stream a Max file attachment from *url* directly to *destination*.

    Returns ``True`` on success and ``False`` on failure.
    """
    dst = Path(destination)
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with dst.open("wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
            return True
    except Exception:
        logging.exception("Failed to download Max file from %s...", url[:80])
        try:
            if dst.exists():
                dst.unlink()
        except Exception:
            logging.exception("Failed to cleanup partially downloaded file %s", dst)
        return False
