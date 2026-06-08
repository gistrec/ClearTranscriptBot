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


@app.get("/healthcheck")
async def healthcheck():
    problems: dict[str, object] = {}

    stale = overdue()
    if stale:
        problems["stale_loops"] = {name: round(age, 1) for name, age in stale.items()}

    try:
        ping_db()
    except Exception as exc:
        logging.exception("Healthcheck: database ping failed")
        problems["database"] = repr(exc)

    if problems:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "problems": problems})
    return {"status": "ok"}


async def start_healthcheck_server() -> None:
    config = uvicorn.Config(app, host="0.0.0.0", port=9000, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()
