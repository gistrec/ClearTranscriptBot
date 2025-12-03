"""VK Ads integration helpers."""

import logging
import os

import httpx

from database.queries import get_vk_click


VK_COUNTER_ID = os.getenv("VK_COUNTER_ID", "3723500")
TRACKER_URL = "https://top-fwz1.mail.ru/tracker"
HTTP_TIMEOUT = 5.0


async def track_vk_goal(token: str, goal: str = "startBot") -> bool:
    """Send conversion event for a VK Ads click token.

    The *token* refers to the compact identifier returned to the user and mapped
    to the original ``rb_clickid`` stored in the database.
    """

    click = get_vk_click(token)
    if click is None:
        logging.info("VK Ads token not found: %s", token)
        return False

    params = {
        "id": VK_COUNTER_ID,
        "e": f"RG%3A0/{goal}",
        "rb_clickid": click.rb_clickid,
    }

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(TRACKER_URL, params=params)
            response.raise_for_status()
        logging.info("VK Ads goal sent: token=%s goal=%s", token, goal)
        return True
    except Exception as exc:  # noqa: BLE001
        logging.warning(
            "VK Ads goal failed: token=%s goal=%s error=%s", token, goal, exc
        )
        return False
