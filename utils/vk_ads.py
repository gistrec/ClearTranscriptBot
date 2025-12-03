"""VK Ads integration helpers."""

import logging
import os

import httpx

from database.queries import get_vk_click


VK_COUNTER_ID = os.getenv("VK_COUNTER_ID", "3723500")
TRACKER_URL = "https://top-fwz1.mail.ru/tracker"
HTTP_TIMEOUT = 5.0


async def track_vk_goal(token: str, goal: str = "startBot") -> bool:
    """
    Send conversion event for a VK Ads click token via Top.Mail.ru tracker.

    *token* — короткий токен, под которым хранится реальный rb_clickid.
    """

    # 1. Достаём запись по токену
    click = get_vk_click(token)
    if click is None:
        logging.info("VK Ads: token not found: %s", token)
        return False

    rb_clickid = click.rb_clickid
    logging.info("VK Ads: resolved token=%s → rb_clickid=%s", token, rb_clickid)

    # 2. Формируем правильный формат цели (НЕ URL-энкодить!)
    # e=RG:0/startBot
    e_param = f"RG:0/{goal}"

    # 3. Собираем URL вручную — params нельзя использовать
    url = (
        f"{TRACKER_URL}"
        f"?id={VK_COUNTER_ID};"
        f"e={e_param};"
        f"rb_clickid={rb_clickid}"
    )

    logging.info("VK Ads: final tracker URL: %s", url)

    # 4. Выполняем запрос
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(url)
            response.raise_for_status()

        logging.info(
            "VK Ads: goal sent successfully: goal=%s, rb_clickid=%s, status=%s",
            goal, rb_clickid, response.status_code
        )
        return True

    except Exception as exc:  # noqa: BLE001
        logging.warning(
            "VK Ads: goal send FAILED: goal=%s rb_clickid=%s error=%r url=%s",
            goal, rb_clickid, exc, url
        )
        return False
