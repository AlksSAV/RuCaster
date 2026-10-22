"""RuCaster — точка входа."""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.api import router as api_router
from app.core.config import settings
from app.db.session import close_db, init_db
from app.ntrip.hub import NtripHub
from app.ntrip.server import NtripServer
from app.ws.hub import ws_hub

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("rucaster")


class AppContext:
    """Глобальный контекст приложения."""

    def __init__(self) -> None:
        self.ntrip_hub: NtripHub | None = None
        self.ntrip_server: NtripServer | None = None
        self._shutdown_event = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ctx = AppContext()
    app.state.ctx = ctx

    # Инициализация БД
    settings.ensure_dirs()
    await init_db()
    log.info("Database initialized")

    # NTRIP сервер
    ctx.ntrip_hub = NtripHub()
    ctx.ntrip_server = NtripServer(ctx.ntrip_hub)
    await ctx.ntrip_server.start()
    log.info("NTRIP server started on %s:%s", settings.ntrip_host, settings.ntrip_port)

    # SIGINT/SIGTERM
    def _signal_handler() -> None:
        log.info("Shutdown signal received")
        ctx._shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass  # Windows

    yield

    # Shutdown
    log.info("Shutting down...")
    if ctx.ntrip_server:
        await ctx.ntrip_server.stop()
    await close_db()
    log.info("Shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

app.include_router(api_router)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws_hub.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            # echo back для теста, дальше сюда придут команды
            await ws.send_text(data)
    except WebSocketDisconnect:
        await ws_hub.disconnect(ws)


@app.get("/health")
async def health():
    ctx: AppContext = app.state.ctx
    return {
        "status": "ok",
        "ntrip_running": ctx.ntrip_server.running if ctx.ntrip_server else False,
        "ws_clients": ws_hub.client_count,
    }


def cli() -> None:
    """CLI entry point: rucaster."""
    uvicorn.run(
        "app.main:app",
        host=settings.http_host,
        port=settings.http_port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )


if __name__ == "__main__":
    cli()
