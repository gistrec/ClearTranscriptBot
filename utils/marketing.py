import os
import time
import httpx
import logging

from typing import Dict, Any


COUNTER_ID   = os.getenv("COUNTER_ID")  # ID счётчика Яндекс.Метрики
MEAS_TOKEN   = os.getenv("MEAS_TOKEN")  # Measurement Protocol токен (создаётся в настройках счётчика)
BOT_URL      = os.getenv("BOT_URL", "https://t.me/ClearTranscriptBot")  # Публичный URL бота
MP_COLLECT   = "https://mc.yandex.ru/collect/"
HTTP_TIMEOUT = 5.0


async def track_goal(yclid: str, goal: str) -> bool:
    """
    Асинхронная отправка визита (pageview) + события (event) в Яндекс.Метрику.

    :param yclid: идентификатор рекламного клика (например, из /start <yclid>)
    :param goal: название цели в Метрике (например, "startbot", "resultbot")
    :return: True при успехе, False при ошибке
    """
    logging.info("Metrica: track_goal yclid=%s goal=%s", yclid, goal)

    if not MEAS_TOKEN or not COUNTER_ID:
        logging.info("Metrica disabled: MEAS_TOKEN or COUNTER_ID not set")
        return False

    ts = int(time.time())
    dl = f"{BOT_URL}?yclid={yclid}"
    dr = "https://yabs.yandex.ru"

    # 1) pageview — создаём/дополняем визит
    pv: Dict[str, Any] = {
        "tid": COUNTER_ID,  # tid — идентификатор счётчика (Counter ID)
        "cid": yclid,       # cid — идентификатор клиента (в нашем случае YCLID)
        "t":   "pageview",  # t — тип хита ("pageview" = просмотр страницы)
        "dr":  dr,    # dr — document referrer (источник перехода)
        "dl":  dl,    # dl = document location (URL страницы/экрана визита)
        "dt":  goal,  # dt — document title (название "страницы", можно указать имя цели)
        "et":  ts,    # et — event time (время события, unix timestamp в секундах)
        "ms":  MEAS_TOKEN,  # ms — measurement protocol token
    }

    # 2) event — сама конверсия
    ev: Dict[str, Any] = {
        "tid": COUNTER_ID,  # tid — идентификатор счётчика
        "cid": yclid,       # cid — идентификатор клиента
        "t":   "event",     # t — тип хита ("event" = событие)
        "ea":  goal,        # ea — event action (действие события, обычно имя цели)
        "et":  ts,          # et — event time
        "dl":  dl,          # dl — document location (адрес, к которому привязываем событие)
        "ms":  MEAS_TOKEN,  # ms — measurement protocol token
    }

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r1 = await client.get(MP_COLLECT, params=pv)
            r1.raise_for_status()

            r2 = await client.get(MP_COLLECT, params=ev)
            r2.raise_for_status()

        logging.info("Metrica OK: yclid=%s goal=%s", yclid, goal)
        return True
    except Exception as e:
        logging.warning("Metrica failed: yclid=%s goal=%s err=%s", yclid, goal, e)
        return False
