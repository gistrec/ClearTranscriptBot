"""File download utility for Max messenger attachments."""
import asyncio
import logging
from pathlib import Path

import httpx

from utils.sentry import sentry_span


@sentry_span(op="max.download_file")
async def download_max_file(url: str, destination: str | Path) -> bool:
    """Stream a Max file attachment from *url* directly to *destination*.

    okcdn.ru sometimes closes the response stream before the body is
    complete (httpx.RemoteProtocolError); retry once before giving up.

    Returns ``True`` on success and ``False`` on failure.
    """
    dst = Path(destination)
    for attempt in range(2):
        if attempt:
            await asyncio.sleep(1.0)
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with dst.open("wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
            return True
        except httpx.RemoteProtocolError as exc:
            if attempt == 0:
                logging.warning("Max file CDN closed mid-stream, retrying: %s", exc)
                continue
            logging.warning("Max file CDN closed mid-stream after retry: %s", exc)
            break
        except Exception:
            logging.exception("Failed to download Max file from %s...", url[:80])
            break

    try:
        if dst.exists():
            dst.unlink()
    except Exception:
        logging.exception("Failed to cleanup partially downloaded file %s", dst)
    return False
