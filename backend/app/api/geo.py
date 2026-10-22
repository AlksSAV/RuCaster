"""Geo API: UTM, удалённые станции и mountpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db.schemas import RemoteMountpointResponse, RemoteStationResponse, UTMResponse
from app.gnss.parsers import wgs84_to_utm

router = APIRouter()


@router.get("/to-utm", response_model=UTMResponse)
async def to_utm(lat: float, lon: float):
    """Преобразовать WGS84 в UTM."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(400, "координаты вне диапазона")
    r = wgs84_to_utm(lat, lon)
    return UTMResponse(**r)


@router.get("/remote-station", response_model=RemoteStationResponse)
async def remote_station(
    host: str,
    port: int,
    mountpoint: str,
    user: str,
    password: str,
    gga_lat: float | None = None,
    gga_lon: float | None = None,
    timeout: float = 15.0,
):
    """Получить координаты станции с чужого кастера."""
    # TODO: реализовать подключение к удалённому кастеру и чтение 1005/1006
    return RemoteStationResponse(found=False)


@router.get("/remote-mountpoints", response_model=RemoteMountpointResponse)
async def remote_mountpoints(
    host: str,
    port: int,
    user: str = "",
    password: str = "",
):
    """Получить список mountpoints с чужого кастера."""
    # TODO: реализовать запрос sourcetable
    return RemoteMountpointResponse(mountpoints=[])
