"""Geo API: UTM, удалённые станции и mountpoints (T-011)."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException

from app.db.schemas import RemoteMountpointResponse, RemoteStationResponse, UTMResponse
from app.gnss.parsers import wgs84_to_utm
from app.services import geo

log = logging.getLogger("rucaster.api.geo")

router = APIRouter()


def _validate_host_port(host: str, port: int) -> None:
    if not host or len(host) > 253:
        raise HTTPException(400, "некорректный host")
    if not (1 <= port <= 65535):
        raise HTTPException(400, "порт вне диапазона 1..65535")


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
    """Получить координаты станции с чужого кастера.

    Сначала sourcetable (быстрый путь), затем RTCM 1005/1006 из потока mountpoint.
    """
    _validate_host_port(host, port)
    if not mountpoint:
        raise HTTPException(400, "пустой mountpoint")
    timeout = max(1.0, min(timeout, 60.0))

    try:
        coords = await geo.fetch_station_coords(
            host, port, mountpoint, user=user, password=password, timeout=timeout
        )
    except (TimeoutError, httpx.TimeoutException):
        raise HTTPException(504, "таймаут подключения к кастеру") from None
    except (OSError, httpx.HTTPError) as exc:
        log.warning("remote-station failed for %s:%d/%s: %s", host, port, mountpoint, exc)
        raise HTTPException(502, "не удалось подключиться к кастеру") from None

    if coords is None:
        return RemoteStationResponse(found=False)

    ecef = None
    try:
        import pyrtcm

        ecef = tuple(
            round(v, 4)
            for v in pyrtcm.llh2ecef(coords["latitude"], coords["longitude"], coords["height"])
        )
    except Exception:  # noqa: BLE001 — ecef необязателен
        ecef = None

    return RemoteStationResponse(
        found=True,
        ecef=ecef,
        latitude=coords["latitude"],
        longitude=coords["longitude"],
        height=coords["height"],
    )


@router.get("/remote-mountpoints", response_model=RemoteMountpointResponse)
async def remote_mountpoints(
    host: str,
    port: int,
    user: str = "",
    password: str = "",
):
    """Получить список mountpoints с чужого кастера (sourcetable)."""
    _validate_host_port(host, port)

    try:
        entries = await geo.fetch_sourcetable(host, port)
    except (TimeoutError, httpx.TimeoutException):
        raise HTTPException(504, "таймаут подключения к кастеру") from None
    except (OSError, httpx.HTTPError) as exc:
        log.warning("remote-mountpoints failed for %s:%d: %s", host, port, exc)
        raise HTTPException(502, "не удалось подключиться к кастеру") from None

    if entries is None:
        raise HTTPException(502, "sourcetable недоступен")

    return RemoteMountpointResponse(
        mountpoints=[
            {
                "mountpoint": e.mountpoint,
                "format": e.fmt,
                "nav_system": e.nav_system,
                "latitude": e.latitude,
                "longitude": e.longitude,
                "height": e.height,
            }
            for e in entries
        ]
    )
