"""Monitoring API: status, clients, positions, connections, statistics."""

from __future__ import annotations

from fastapi import APIRouter

from app.db.schemas import (
    ClientResponse,
    ConnectionResponse,
    PositionResponse,
    StatisticsResponse,
    StatusResponse,
)

router = APIRouter()


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """Текущий статус кастера."""
    # TODO: подключить к реальным данным NtripHub
    return StatusResponse()


@router.get("/connections", response_model=list[ConnectionResponse])
async def get_connections(limit: int = 50):
    """Кольцевой журнал подключений."""
    # TODO: вернуть последние N записей
    return []


@router.get("/clients", response_model=list[ClientResponse])
async def get_clients():
    """Подключённые клиенты (роверы)."""
    # TODO: вернуть из NtripHub
    return []


@router.get("/positions", response_model=list[PositionResponse])
async def get_positions():
    """Позиции роверов (из GGA)."""
    # TODO: вернуть из парсера GGA
    return []


@router.get("/statistics", response_model=StatisticsResponse)
async def get_statistics():
    """Накопительная статистика."""
    return StatisticsResponse()
