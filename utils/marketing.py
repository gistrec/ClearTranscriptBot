import os
import time
import asyncio
import httpx
import logging

from typing import Dict, Any


COUNTER_ID   = os.getenv("COUNTER_ID")  # ID счётчика Яндекс.Метрики
MEAS_TOKEN   = os.getenv("MEAS_TOKEN")  # Measurement Protocol токен (создаётся в настройках счётчика)
SITE_URL     = "https://clear-transcript-bot.ru/"  # Домен счётчика Метрики — идёт в dl (document location)
MP_COLLECT   = "https://mc.yandex.ru/collect/"
HTTP_TIMEOUT = 5.0

# Конверсии уходят в атрибуцию Яндекс.Директа, поэтому потерянный хит искажает
# CPA/ROI. Транзиентные сбои (таймауты, сеть, 5xx) ретраим с нарастающей паузой,
# пока не отправится; сдаёмся только на постоянных 4xx, которые ретрай не лечит.
# Бэкофф: 1,2,4,8,16,32,60,60... — 12 попыток это ~6 минут перед сдачей.
MAX_ATTEMPTS = 12
MAX_BACKOFF  = 60.0


async def _send_hit(client: httpx.AsyncClient, params: Dict[str, Any], label: str) -> bool:
    """Отправить один хит в Метрику, ретраить транзиентные сбои до успеха."""
    backoff = 1.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = await client.get(MP_COLLECT, params=params)
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            # 429 (rate limit) и 408 — транзиентные 4xx, их ретраим. Остальные
            # 4xx (400/401/403/404) — непринятый хит: тот же payload даст тот же
            # ответ (см. CLEAR-TRANSCRIPT-4T: один yclid → 400 дважды за 34 мин),
            # поэтому сдаёмся сразу, и это всплывёт в Sentry как потерянный хит.
            if 400 <= status < 500 and status not in (408, 429):
                logging.warning("Metrica %s rejected (%s), not retrying", label, status)
                return False
            logging.warning("Metrica %s attempt %d/%d failed: %s", label, attempt, MAX_ATTEMPTS, exc)
        except Exception as exc:
            logging.warning("Metrica %s attempt %d/%d failed: %s", label, attempt, MAX_ATTEMPTS, exc)
        if attempt < MAX_ATTEMPTS:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)
    return False


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
    dl = f"{SITE_URL}?yclid={yclid}"
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

    # Хиты независимы: успешный pageview не переотправляется, если упал event.
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        ok_pv = await _send_hit(client, pv, "pageview")
        ok_ev = await _send_hit(client, ev, "event")

    if ok_pv and ok_ev:
        logging.info("Metrica OK: yclid=%s goal=%s", yclid, goal)
        return True

    # Конверсия (event) не доехала даже после ретраев — это реально потерянный
    # сигнал, поднимаем до error, чтобы увидеть в Sentry. Недослать только
    # pageview менее критично — оставляем warning.
    if not ok_ev:
        logging.error("Metrica event lost after retries: yclid=%s goal=%s", yclid, goal)
    else:
        logging.warning("Metrica pageview lost after retries: yclid=%s goal=%s", yclid, goal)
    return False
