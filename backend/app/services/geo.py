"""Geo-утилиты: ECEF→WGS84, парсинг sourcetable и RTCM 1005/1006 (T-011)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import pyrtcm

log = logging.getLogger("rucaster.geo")

# Sourcetable: строки STR;... (NTRIP v1) и SOURCELOG;... (NTRIP v2).
# Поля разделяются ';', при этом identifier/format содержат пробелы, а
# latitude/longitude — собственные значения вида "DDMM.MM,N".
_SOURCETABLE_PREFIXES = ("STR;", "SOURCELOG;")


def _dms_to_deg(value: float, hemi: str) -> float:
    """DMS (DDMM.MMMM) -> десятичные градусы."""
    d = int(value / 100)
    m = value - d * 100
    result = d + m / 60.0
    if hemi in ("S", "W"):
        result = -result
    return result


def _parse_coord(field: str) -> tuple[float | None, str | None]:
    """Разобрать поле координаты sourcetable: 'DDMM.MM,N' -> (DMS, hemisphere)."""
    parts = field.split(",")
    if len(parts) < 2:
        return None, None
    try:
        value = float(parts[0])
    except ValueError:
        return None, None
    hemi = parts[1].strip().upper()
    if hemi not in ("N", "S", "E", "W"):
        return value, None
    return value, hemi


@dataclass
class SourcetableEntry:
    mountpoint: str
    identifier: str
    fmt: str
    nav_system: str
    latitude: float | None = None
    longitude: float | None = None
    height: float | None = None
    antenna: str | None = None
    receiver: str | None = None
    mp_type: str | None = None
    comment: str | None = None


def parse_sourcetable(text: str) -> list[SourcetableEntry]:
    """Распарсить sourcetable (NTRIP v1 STR; и v2 SOURCELOG;).

    Поля разделяются ';'. Поле координаты содержит внутреннюю запятую с
    полушарием ("DDMM.MM,N"), поэтому split по ';' корректен, а координаты
    разбираются отдельно.
    """
    entries: list[SourcetableEntry] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith(_SOURCETABLE_PREFIXES):
            continue
        f = line.split(";")
        if len(f) < 8:
            continue
        lat_v, lat_h = _parse_coord(f[5])
        lon_v, lon_h = _parse_coord(f[6])
        try:
            alt = float(f[7])
        except ValueError:
            alt = None
        entries.append(
            SourcetableEntry(
                mountpoint=f[1],
                identifier=f[2],
                fmt=f[3],
                nav_system=f[4],
                latitude=_dms_to_deg(lat_v, lat_h) if lat_v is not None and lat_h else None,
                longitude=_dms_to_deg(lon_v, lon_h) if lon_v is not None and lon_h else None,
                height=alt,
                antenna=f[12] if len(f) > 12 else None,
                receiver=f[13] if len(f) > 13 else None,
                mp_type=f[14] if len(f) > 14 else None,
                comment=";".join(f[15:]).strip() if len(f) > 15 else None,
            )
        )
    return entries


# ---------- ECEF → WGS84 (pyrtcm) ----------


def ecef_to_wgs84(x: float, y: float, z: float) -> dict[str, float]:
    """ECEF (метры) → lat, lon, height (WGS84)."""
    lat, lon, h = pyrtcm.ecef2llh(x, y, z)
    return {"latitude": round(lat, 7), "longitude": round(lon, 7), "height": round(h, 3)}


# ---------- Парсеры RTCM 1005/1006 (через pyrtcm) ----------


def _decode_arp(payload: bytes) -> dict[str, float] | None:
    """Распарсить RTCM 1005/1006 через pyrtcm, вернуть lat/lon/height.

    pyrtcm отдаёт ECEF-координаты станции в атрибутах DF025/DF026/DF027 (метры),
    высота антенны (только 1006) — в DF028.
    """
    try:
        msg = pyrtcm.RTCMMessage(payload)
    except (pyrtcm.RTCMMessageError, pyrtcm.RTCMTypeError, KeyError):
        return None

    try:
        x = float(msg.DF025)
        y = float(msg.DF026)
        z = float(msg.DF027)
    except AttributeError:
        return None

    lat, lon, h = pyrtcm.ecef2llh(x, y, z)
    result = {
        "latitude": round(lat, 7),
        "longitude": round(lon, 7),
        "height": round(h, 3),
    }
    if hasattr(msg, "DF028"):
        result["antenna_height"] = round(float(msg.DF028), 4)
    return result


def parse_rtcm1005(payload: bytes) -> dict[str, float] | None:
    """Распарсить RTCM 1005 (Stationary ARP, ECEF)."""
    return _decode_arp(payload)


def parse_rtcm1006(payload: bytes) -> dict[str, float] | None:
    """Распарсить RTCM 1006 (Stationary ARP + Antenna Height, ECEF)."""
    return _decode_arp(payload)


# ---------- TCP-подключение к NTRIP-кастеру ----------


async def connect_ntrip_source(
    host: str,
    port: int,
    mountpoint: str,
    user: str,
    password: str,
    timeout: float = 15.0,
) -> bytes | None:
    """Подключиться к mountpoint по NTRIP, получить первый чанк данных.

    Возвращает сырые байты потока или None при ошибке/таймауте.
    """
    import base64

    auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    request = (
        f"GET /{mountpoint} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Icecast: 2.0\r\n"
        f"Authorization: Basic {auth}\r\n"
        f"Accept: */*\r\n"
        f"User-Agent: RuCaster-geo\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode()

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
    except (TimeoutError, OSError) as exc:
        log.warning("NTRIP connect failed %s:%d/%s: %s", host, port, mountpoint, exc)
        return None

    try:
        writer.write(request)
        await writer.drain()

        # Прочитать HTTP-ответ (пропустить заголовки)
        buf = bytearray()
        deadline = asyncio.get_event_loop().time() + timeout
        while b"\r\n\r\n" not in buf:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return None
            chunk = await asyncio.wait_for(reader.read(4096), timeout=remaining)
            if not chunk:
                return None
            buf.extend(chunk)

        # Проверить статус
        header_end = buf.find(b"\r\n\r\n")
        header = buf[:header_end].decode(errors="replace").lower()
        if "200" not in header:
            log.warning("NTRIP non-200: %s", header[:100])
            return None

        # Пропустить заголовки
        data = buf[header_end + 4:]

        # Читать данные пока есть (до таймаута)
        while asyncio.get_event_loop().time() < deadline:
            try:
                chunk = await asyncio.wait_for(reader.read(65536), timeout=1.0)
                if not chunk:
                    break
                data += chunk
            except TimeoutError:
                break

        return bytes(data)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


# ---------- Высокоуровневые функции ----------


async def fetch_sourcetable(
    host: str, port: int, timeout: float = 10.0
) -> list[SourcetableEntry] | None:
    """Получить и распарсить sourcetable внешнего кастера через HTTP."""
    import httpx

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"http://{host}:{port}/", follow_redirects=True)
        if resp.status_code != 200:
            log.warning("sourcetable fetch failed %s:%d: %d", host, port, resp.status_code)
            return None
        return parse_sourcetable(resp.text)


async def fetch_station_coords(
    host: str, port: int, mountpoint: str, user: str = "", password: str = "", timeout: float = 15.0
) -> dict[str, float] | None:
    """Получить координаты станции mountpoint: sourcetable или RTCM 1005/1006."""
    # 1. Sourcetable — быстрый путь
    entries = await fetch_sourcetable(host, port, timeout)
    if entries is not None:
        for e in entries:
            if e.mountpoint != mountpoint:
                continue
            # GGA-маунт: координат нет или они нулевые — идём к RTCM
            if (
                e.latitude is not None
                and e.longitude is not None
                and (e.latitude != 0.0 or e.longitude != 0.0)
            ):
                return {
                    "latitude": e.latitude,
                    "longitude": e.longitude,
                    "height": e.height or 0.0,
                }
            break

    # 2. Подключение к mountpoint и парсинг RTCM 1005/1006
    data = await connect_ntrip_source(host, port, mountpoint, user, password, timeout)
    if data is None:
        return None

    # Ищем кадры 1006 (приоритет: есть antenna height) и 1005
    from app.gnss.parsers import parse_rtcm3

    found: dict[int, bytes] = {}
    for frame in parse_rtcm3(data):
        if frame.msg_type in (1005, 1006) and frame.crc_ok:
            if frame.msg_type == 1006 and 1006 not in found:
                found[1006] = frame.data
            elif frame.msg_type == 1005 and 1005 not in found:
                found[1005] = frame.data

    if 1006 in found:
        result = parse_rtcm1006(found[1006])
        if result is not None:
            result.pop("antenna_height", None)
            return result
    if 1005 in found:
        return parse_rtcm1005(found[1005])
    return None
