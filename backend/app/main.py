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
from app.core.security import decode_access_token
from app.db.session import close_db, init_db
from app.ntrip.hub import NtripHub
from app.ntrip.server import NtripServer
from app.services.proxy_service import ProxyService
from app.services.recorder import RecordManager
from app.ws.hub import ws_hub

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("rucaster")


async def _restore_proxies(ctx: AppContext) -> None:
    """Восстановить proxy из БД при старте."""
    from sqlalchemy import select

    from app.db.models import ProxyModel
    from app.db.session import session_scope

    ps = ctx.proxy_service
    if not ps:
        return

    try:
        async with session_scope() as session:
            rows = (
                (await session.execute(select(ProxyModel).where(ProxyModel.is_active)))
                .scalars()
                .all()
            )
    except Exception:
        log.warning("Failed to restore proxy from DB", exc_info=True)
        return

    for p in rows:
        ps.add_proxy(
            proxy_id=p.id,
            owner_id=p.owner_id,
            source_mountpoint=p.source_mountpoint,
            target_mountpoint=p.target_mountpoint,
            mode=p.mode,
            serve_mountpoint=p.serve_mountpoint,
            dest_port=p.dest_port,
            x=p.x,
            y=p.y,
            z=p.z,
            de=p.de,
            dn=p.dn,
            du=p.du,
            relay_host=p.relay_host,
            relay_port=p.relay_port,
            relay_mountpoint=p.relay_mountpoint,
            relay_user=p.relay_user,
            relay_password=p.relay_password,
        )
        if p.mode == "relay" and p.relay_host and p.relay_mountpoint:
            await ps.activate_relay(
                source_mountpoint=p.source_mountpoint,
                target_mountpoint=p.target_mountpoint,
                src_host=p.relay_host,
                src_port=p.relay_port or 2101,
                src_mountpoint=p.relay_mountpoint,
                src_user=p.relay_user or "",
                src_password=p.relay_password or "",
            )


class AppContext:
    """Глобальный контекст приложения."""

    def __init__(self) -> None:
        self.ntrip_hub: NtripHub | None = None
        self.ntrip_server: NtripServer | None = None
        self.record_manager: RecordManager | None = None
        self.proxy_service: ProxyService | None = None
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

    # T-007: менеджер записей статики
    ctx.record_manager = RecordManager(
        hub=ctx.ntrip_hub,
        root=settings.records_dir,
        retention_days=settings.retention_days,
        default_duration=settings.default_record_duration_s,
        max_duration=settings.max_record_duration_s,
    )
    ctx.record_manager.start_retention()

    # T-008: proxy-сервис (двусторонняя связь с hub для relay-рассылки)
    ctx.proxy_service = ProxyService()
    ctx.proxy_service.hub = ctx.ntrip_hub
    ctx.ntrip_hub.proxy_service = ctx.proxy_service
    # Восстановить proxy из БД
    await _restore_proxies(ctx)
    log.info("Proxy service initialized")

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
    if ctx.record_manager:
        await ctx.record_manager.shutdown()
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
    # T-006: авторизация по JWT из cookie ntrip_session
    token = ws.cookies.get("ntrip_session")
    username = decode_access_token(token) if token else None
    if not username:
        # 4401 — не авторизован; фронтенд не должен переподключаться
        await ws.close(code=4401)
        return

    await ws_hub.connect(ws, username=username)
    try:
        while True:
            data = await ws.receive_text()
            # Команды клиента: только ping (keep-alive). Прочее игнорируем.
            if data.strip() == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    finally:
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
