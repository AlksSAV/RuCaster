"""Monitoring API: status, clients, positions, connections, statistics, analysis."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.config import settings
from app.db.models import SourceModel, UserModel
from app.db.schemas import (
    ClientResponse,
    ConnectionResponse,
    PositionResponse,
    StatisticsResponse,
    StatusResponse,
    StatusSource,
)
from app.db.session import get_session

router = APIRouter()


@router.get("/status", response_model=StatusResponse)
async def get_status(request: Request):
    """Текущий статус кастера."""
    ctx = request.app.state.ctx
    hub = ctx.ntrip_hub
    stats = await hub.get_status()

    # sources — из БД, флаг alive берётся из активных сессий hub
    sources = [StatusSource(**s) for s in stats["sources"]]
    alive_sources = sum(1 for s in sources if s.alive)
    return StatusResponse(
        status="ONLINE" if alive_sources else "OFFLINE",
        host=settings.ntrip_host,
        port=settings.ntrip_port,
        running=ctx.ntrip_server.running if ctx.ntrip_server else False,
        sources=sources,
        clients=stats["clients"],
        total_clients=stats["total_clients"],
        active_connections=alive_sources + stats["total_clients"],
        rejected_connections=stats["rejected_connections"],
        max_connections=settings.max_connections,
        max_connections_per_ip=settings.max_connections_per_ip,
    )


@router.get("/connections", response_model=list[ConnectionResponse])
async def get_connections(request: Request, limit: int = 50):
    """Кольцевой журнал подключений."""
    entries = request.app.state.ctx.ntrip_hub.get_connections(limit)
    return [
        ConnectionResponse(
            id=e["id"],
            type=e["type"],
            mountpoint=e["mountpoint"],
            ip_address=e["ip_address"],
            connected_at=e["connected_at"],
            disconnected_at=e["disconnected_at"],
            bytes_sent=e["bytes_sent"],
            bytes_received=e["bytes_received"],
        )
        for e in entries
    ]


@router.get("/clients", response_model=list[ClientResponse])
async def get_clients(request: Request):
    """Подключённые клиенты (роверы)."""
    clients = request.app.state.ctx.ntrip_hub.get_clients()
    return [ClientResponse(**c) for c in clients]


@router.get("/positions", response_model=list[PositionResponse])
async def get_positions(request: Request):
    """Позиции роверов (из GGA — T-005)."""
    positions = request.app.state.ctx.ntrip_hub.get_positions()
    return [
        PositionResponse(
            mountpoint=p["mountpoint"],
            ip=p["ip"],
            latitude=p["latitude"],
            longitude=p["longitude"],
            fix_quality=p["fix_quality"],
            num_sats=p["num_sats"],
            hdop=p["hdop"],
            altitude=p["altitude"],
            geoid_sep=p["geoid_sep"],
            age=p["age"],
            updated_at=p["updated_at"],
            age_seconds=p["age_seconds"],
        )
        for p in positions
    ]


@router.get("/statistics", response_model=StatisticsResponse)
async def get_statistics(request: Request):
    """Накопительная статистика."""
    stats = await request.app.state.ctx.ntrip_hub.get_statistics()
    return StatisticsResponse(**stats)


@router.get("/analysis/{mountpoint}")
async def get_analysis(
    mountpoint: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: UserModel = Depends(get_current_user),
):
    """RTCM-анализ потока источника за скользящее окно 60 с (T-009).

    Доступен владельцу источника или админу. 404 — источник не существует,
    409 — поток ещё не наблюдался (окно пусто).
    """
    stmt = select(SourceModel).where(SourceModel.mountpoint == mountpoint)
    source = (await session.execute(stmt)).scalar_one_or_none()
    if not source:
        raise HTTPException(404, "источник не найден")
    if source.owner_id != user.id and user.role != "admin":
        raise HTTPException(403, "нет доступа к анализу чужого источника")

    hub = request.app.state.ctx.ntrip_hub
    result = hub.get_analysis(mountpoint)
    if result is None:
        raise HTTPException(409, "поток ещё не наблюдался")
    return result
