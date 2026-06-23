"""FastAPI healthcheck server on port 9000.

Deep check: returns 503 when a critical loop has stopped ticking or the database
is unreachable, so an external GET monitor catches the silent-failure case
("process alive but bot broken"), not just a hard crash. Defined as async so the
check is itself subject to event-loop health — a frozen loop fails the probe.
"""
import logging

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from database.queries import ping_db
from utils.heartbeat import overdue

app = FastAPI()

_unhealthy = False


@app.get("/healthcheck")
async def healthcheck():
    global _unhealthy
    problems: dict[str, object] = {}

    stale = overdue()
    if stale:
        problems["stale_loops"] = {name: round(age, 1) for name, age in stale.items()}

    try:
        ping_db()
    except Exception as exc:
        problems["database"] = repr(exc)

    if problems:
        # Probed every few seconds and the 503 persists for the whole incident,
        # so log the breakdown only on the healthy -> unhealthy edge, not per probe.
        if not _unhealthy:
            logging.warning("Healthcheck returning 503, unhealthy: %s", problems)
        _unhealthy = True
        return JSONResponse(status_code=503, content={"status": "unhealthy", "problems": problems})

    if _unhealthy:
        logging.info("Healthcheck recovered, returning 200")
    _unhealthy = False
    return {"status": "ok"}


async def start_healthcheck_server() -> None:
    config = uvicorn.Config(app, host="0.0.0.0", port=9000, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()
