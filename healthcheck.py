"""FastAPI healthcheck server on port 9000."""
import uvicorn
from fastapi import FastAPI

app = FastAPI()


@app.get("/healthcheck")
async def healthcheck():
    return {"status": "ok"}


async def start_healthcheck_server() -> None:
    config = uvicorn.Config(app, host="0.0.0.0", port=9000, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()
