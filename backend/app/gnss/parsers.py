"""GNSS: парсеры RTCM3, NMEA GGA, конвертации."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("rucaster.gnss")


@dataclass
class NmeaGGA:
    """Распарсенный NMEA GGA."""

    fix_quality: int = 0
    latitude: float = 0.0
    longitude: float = 0.0
    num_sats: int = 0
    hdop: float = 0.0
    altitude: float = 0.0
    geoid_sep: float = 0.0
    age: float = 0.0


def parse_gga(sentence: str) -> NmeaGGA | None:
    """Парсить $GNGGA или $GPGGA строку.

    Формат: $GNGGA,time,lat,N/S,lon,E/W,quality,sats,hdop,alt,M,geoid,M,age,station*cs
    """
    if not sentence.startswith("$"):
        return None
    parts = sentence.split(",")
    if len(parts) < 15:
        return None

    try:
        quality = int(parts[6])
        if quality == 0:
            return None

        lat = _parse_dmm(parts[2], parts[3])
        lon = _parse_dmm(parts[4], parts[5])
        sats = int(parts[7]) if parts[7] else 0
        hdop = float(parts[8]) if parts[8] else 0.0
        alt = float(parts[9]) if parts[9] else 0.0
        geoid = float(parts[11]) if parts[11] else 0.0
        age = float(parts[13]) if len(parts) > 13 and parts[13] else 0.0

        return NmeaGGA(
            fix_quality=quality,
            latitude=lat,
            longitude=lon,
            num_sats=sats,
            hdop=hdop,
            altitude=alt,
            geoid_sep=geoid,
            age=age,
        )
    except (ValueError, IndexError):
        log.warning("Failed to parse GGA: %s", sentence)
        return None


def _parse_dmm(value: str, hemisphere: str) -> float:
    """Преобразовать DMM (DDMM.MMMM) в десятичные градусы."""
    dmm = float(value)
    degrees = int(dmm / 100)
    minutes = dmm - degrees * 100
    result = degrees + minutes / 60.0
    if hemisphere in ("S", "W"):
        result = -result
    return result


@dataclass
class RtcFrame:
    """Распарсенный RTCM3 кадр."""

    msg_type: int
    length: int
    crc_ok: bool
    data: bytes


def parse_rtcm3(data: bytes) -> list[RtcFrame]:
    """Парсить RTCM3 кадры из байтового потока.

    RTCM3 формат: 0xD3 + length(2 байта) + data(length) + CRC(2 байта)
    """
    frames: list[RtcFrame] = []
    i = 0
    while i < len(data) - 3:
        if data[i] != 0xD3:
            i += 1
            continue

        if i + 3 >= len(data):
            break

        length = (data[i + 1] << 8) | data[i + 2]
        if length < 7 or i + 3 + length > len(data):
            i += 1
            continue

        frame_data = data[i + 3 : i + 3 + length]
        # 12-битный тип сообщения: первый байт + старшие 4 бита второго
        msg_type = (frame_data[0] << 4) | (frame_data[1] >> 4)
        crc_ok = True  # TODO: validate CRC

        frames.append(
            RtcFrame(
                msg_type=msg_type,
                length=length,
                crc_ok=crc_ok,
                data=frame_data,
            )
        )
        i += 3 + length

    return frames


# ---------- WGS84 <-> UTM ----------
def wgs84_to_utm(lat: float, lon: float) -> dict[str, Any]:
    """Преобразовать WGS84 (lat, lon) в UTM."""
    # Упрощённая формула (не для точных измерений)
    a = 6378137.0
    e2 = 0.00669437999014
    k0 = 0.9996

    lon0 = int((lon + 180) / 6) * 6 - 180 + 3
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    lon0_rad = math.radians(lon0)

    N = a / math.sqrt(1 - e2 * math.sin(lat_rad) ** 2)
    T = math.tan(lat_rad) ** 2
    C = e2 / (1 - e2) * math.cos(lat_rad) ** 2
    A = math.cos(lat_rad) * (lon_rad - lon0_rad)

    M = a * (
        (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256) * lat_rad
        - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024) * math.sin(2 * lat_rad)
        + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * math.sin(4 * lat_rad)
        - (35 * e2**3 / 3072) * math.sin(6 * lat_rad)
    )

    x = (
        k0 * N * (A + (1 - T + C) * A**3 / 6 + (5 - 18 * T + T**2 + 72 * C - 58 * e2) * A**5 / 120)
        + 500000
    )
    y = k0 * (
        M
        + N
        * math.tan(lat_rad)
        * (
            A**2 / 2
            + (5 - T + 9 * C + 4 * C**2) * A**4 / 24
            + (61 - 58 * T + T**2 + 600 * C - 330 * e2) * A**6 / 720
        )
    )

    if lat < 0:
        y += 10000000

    zone = int((lon + 180) / 6) + 1
    north = lat >= 0

    return {
        "zone": str(zone),
        "north": north,
        "easting": round(x, 3),
        "northing": round(y, 3),
    }


def utm_to_wgs84(easting: float, northing: float, zone: int, north: bool) -> tuple[float, float]:
    """Обратное преобразование UTM -> WGS84 (формулы Снайдера, USGS)."""
    a = 6378137.0
    e2 = 0.00669437999014
    k0 = 0.9996
    ep2 = e2 / (1 - e2)

    lon0_rad = math.radians((zone - 1) * 6 - 180 + 3)
    x = easting - 500000
    y = northing - 10000000 if not north else northing

    M = y / k0
    mu = M / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))

    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
    )

    sin_phi1 = math.sin(phi1)
    cos_phi1 = math.cos(phi1)
    tan_phi1 = math.tan(phi1)
    C1 = ep2 * cos_phi1**2
    T1 = tan_phi1**2
    N1 = a / math.sqrt(1 - e2 * sin_phi1**2)
    R1 = a * (1 - e2) / (1 - e2 * sin_phi1**2) ** 1.5
    D = x / (N1 * k0)

    lat_rad = phi1 - (N1 * tan_phi1 / R1) * (
        D**2 / 2
        - (5 + 3 * T1 + 10 * C1 - 4 * C1**2 - 9 * ep2) * D**4 / 24
        + (61 + 90 * T1 + 298 * C1 + 45 * T1**2 - 252 * ep2 - 3 * C1**2) * D**6 / 720
    )
    lon_rad = (
        lon0_rad
        + (
            D
            - (1 + 2 * T1 + C1) * D**3 / 6
            + (5 - 2 * C1 + 28 * T1 - 3 * C1**2 + 8 * ep2 + 24 * T1**2) * D**5 / 120
        )
        / cos_phi1
    )

    return round(math.degrees(lat_rad), 7), round(math.degrees(lon_rad), 7)
