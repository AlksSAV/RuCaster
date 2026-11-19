"""Тесты T-011: гео-утилиты (sourcetable, RTCM 1005/1006, ECEF, API).

Сеть не используется: sourcetable/NTRIP подменяются, RTCM-кадры собираются
синтетически в раскладке pyrtcm.
"""

from __future__ import annotations

import bcrypt
import pyrtcm
import pytest
from app.api import geo as geo_api
from app.gnss.parsers import crc24q
from app.services import geo
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# Эталонная станция (Москва)
LAT, LON, H = 55.7558, 37.6173, 200.0


def _bits_uint(val: int, n: int) -> str:
    return format(val & ((1 << n) - 1), "0" + str(n) + "b")


def _bits_int(val: int, n: int) -> str:
    if val < 0:
        val += 1 << n
    return format(val, "0" + str(n) + "b")


def build_1005(x: float, y: float, z: float, station: int = 1234) -> bytes:
    """Payload RTCM 1005 в раскладке полей pyrtcm (X,141,001_1,Y,364,Z)."""
    return _build_arp(1005, x, y, z, station)


def build_1006(x: float, y: float, z: float, ant: float = 1.5) -> bytes:
    """Payload RTCM 1006 (1005 + DF028 Antenna Height, 16 бит)."""
    return _build_arp(1006, x, y, z, ant=ant)


def _build_arp(mid: int, x: float, y: float, z: float, station: int = 1234,
               ant: float | None = None) -> bytes:
    b = _bits_uint(mid, 12) + _bits_uint(station, 12) + _bits_uint(0, 6)
    b += _bits_uint(1, 1) + _bits_uint(0, 1) + _bits_uint(0, 1) + _bits_uint(0, 1)
    b += _bits_int(round(x * 10000), 38) + _bits_uint(0, 1) + _bits_uint(0, 1)
    b += _bits_int(round(y * 10000), 38) + _bits_uint(0, 2)
    b += _bits_int(round(z * 10000), 38)
    if ant is not None:
        b += _bits_uint(round(ant * 10000), 16)
    while len(b) % 8:
        b += "0"
    return int(b, 2).to_bytes(len(b) // 8, "big")


def rtcms_frame(payload: bytes) -> bytes:
    """Обернуть payload в RTCM3-кадр (0xD3 + len + body + CRC)."""
    length = len(payload)
    header = bytes([0xD3, (length >> 8) & 0xFF, length & 0xFF])
    crc = crc24q(header + payload)
    return header + payload + bytes([crc >> 16, (crc >> 8) & 0xFF, crc & 0xFF])


# ---------- sourcetable ----------

SOURCE = """\
ENDSRCH
STR;BASE1;Moscow Base;RTCM 3;4(GPS+GLO);5545.3480,N;03737.0380,E;200.;0;0;0;N;None;0;All;N
STR;ROVER;Rover GGA;RTCM 3;0();0000.0000,N;00000.0000,E;0.;0;0;0;N;None;0;All;G
ENDSTR
"""


class TestSourcetable:
    def test_parse_basic(self):
        entries = geo.parse_sourcetable(SOURCE)
        assert len(entries) == 2
        e = entries[0]
        assert e.mountpoint == "BASE1"
        assert e.latitude == pytest.approx(55.7558, abs=1e-4)
        assert e.longitude == pytest.approx(37.6173, abs=1e-4)
        assert e.height == 200.0

    def test_parse_v2(self):
        text = (
            "SOURCELOG;MP2;id2;RTCM3;4;5545.3480,N;03737.0380,E;100.;0;0;0;N;None;0;All;N\r\n"
            "ENDSRCH"
        )
        entries = geo.parse_sourcetable(text)
        assert entries[0].mountpoint == "MP2"
        assert entries[0].latitude == pytest.approx(55.7558, abs=1e-4)

    def test_empty_and_garbage(self):
        assert geo.parse_sourcetable("") == []
        assert geo.parse_sourcetable("ENDSRCH\r\n") == []

    def test_dms_conversion(self):
        assert geo._dms_to_deg(5545.3480, "N") == pytest.approx(55.7558, abs=1e-4)
        assert geo._dms_to_deg(3737.0380, "E") == pytest.approx(37.6173, abs=1e-4)
        assert geo._dms_to_deg(5545.3480, "S") == pytest.approx(-55.7558, abs=1e-4)


# ---------- ECEF / RTCM ----------


class TestEcef:
    def test_roundtrip(self):
        x, y, z = pyrtcm.llh2ecef(LAT, LON, H)
        r = geo.ecef_to_wgs84(x, y, z)
        assert r["latitude"] == pytest.approx(LAT, abs=1e-5)
        assert r["longitude"] == pytest.approx(LON, abs=1e-5)
        assert r["height"] == pytest.approx(H, abs=1e-2)

    def test_parse_1005(self):
        x, y, z = pyrtcm.llh2ecef(LAT, LON, H)
        r = geo.parse_rtcm1005(build_1005(x, y, z))
        assert r is not None
        assert r["latitude"] == pytest.approx(LAT, abs=1e-5)
        assert r["longitude"] == pytest.approx(LON, abs=1e-5)

    def test_parse_1006_with_antenna(self):
        x, y, z = pyrtcm.llh2ecef(LAT, LON, H)
        r = geo.parse_rtcm1006(build_1006(x, y, z, ant=1.5))
        assert r is not None
        assert r["antenna_height"] == pytest.approx(1.5, abs=1e-3)

    def test_parse_garbage(self):
        assert geo.parse_rtcm1005(b"\x00\x01\x02") is None

    def test_parse_wrong_type(self):
        # кадр 1077 (не ARP) не должен дать координат
        assert geo.parse_rtcm1005(bytes([0x43, 0x00])) is None


# ---------- fetch_station_coords (без сети) ----------


class TestFetchStation:
    async def test_from_sourcetable(self, monkeypatch):
        async def fake_table(host, port, timeout=10.0):
            return geo.parse_sourcetable(SOURCE)

        monkeypatch.setattr(geo, "fetch_sourcetable", fake_table)
        coords = await geo.fetch_station_coords("h", 2101, "BASE1")
        assert coords is not None
        assert coords["latitude"] == pytest.approx(55.7558, abs=1e-4)

    async def test_from_rtcm_when_no_table_coords(self, monkeypatch):
        # sourcetable без координат (ROVER GGA) -> fallback на RTCM
        async def fake_table(host, port, timeout=10.0):
            return geo.parse_sourcetable(SOURCE)

        x, y, z = pyrtcm.llh2ecef(LAT, LON, H)

        async def fake_connect(host, port, mp, user, password, timeout=15.0):
            return rtcms_frame(build_1005(x, y, z))

        monkeypatch.setattr(geo, "fetch_sourcetable", fake_table)
        monkeypatch.setattr(geo, "connect_ntrip_source", fake_connect)
        # ROVER имеет lat=0/lon=0 -> распознан как GGA, идём в RTCM
        coords = await geo.fetch_station_coords("h", 2101, "ROVER")
        assert coords is not None
        assert coords["latitude"] == pytest.approx(LAT, abs=1e-5)

    async def test_1006_preferred(self, monkeypatch):
        async def fake_table(host, port, timeout=10.0):
            return None  # нет sourcetable

        x, y, z = pyrtcm.llh2ecef(LAT, LON, H)

        async def fake_connect(host, port, mp, user, password, timeout=15.0):
            return rtcms_frame(build_1005(x, y, z)) + rtcms_frame(build_1006(x, y, z, 2.0))

        monkeypatch.setattr(geo, "fetch_sourcetable", fake_table)
        monkeypatch.setattr(geo, "connect_ntrip_source", fake_connect)
        coords = await geo.fetch_station_coords("h", 2101, "BASE1")
        assert coords is not None
        # antenna_height удалён на уровне fetch_station_coords
        assert "antenna_height" not in coords

    async def test_not_found(self, monkeypatch):
        async def fake_table(host, port, timeout=10.0):
            return None

        async def fake_connect(host, port, mp, user, password, timeout=15.0):
            return None

        monkeypatch.setattr(geo, "fetch_sourcetable", fake_table)
        monkeypatch.setattr(geo, "connect_ntrip_source", fake_connect)
        assert await geo.fetch_station_coords("h", 2101, "NOPE") is None


# ---------- API ----------


def _fast_hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=4)).decode()


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(geo_api.router, prefix="/api")
    return app


async def _get(app: FastAPI, path: str, params: dict) -> tuple[int, dict]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(path, params=params)
        return r.status_code, (r.json() if r.content else {})


class TestGeoApi:
    async def test_to_utm(self):
        app = _app()
        code, data = await _get(app, "/api/to-utm", {"lat": LAT, "lon": LON})
        assert code == 200
        assert data["zone"] == "37"
        assert data["north"] is True

    async def test_to_utm_out_of_range(self):
        app = _app()
        code, _ = await _get(app, "/api/to-utm", {"lat": 200, "lon": 0})
        assert code == 400

    async def test_remote_mountpoints(self, monkeypatch):
        async def fake_table(host, port, timeout=10.0):
            return geo.parse_sourcetable(SOURCE)

        monkeypatch.setattr(geo, "fetch_sourcetable", fake_table)
        app = _app()
        code, data = await _get(
            app, "/api/remote-mountpoints", {"host": "h", "port": 2101}
        )
        assert code == 200
        names = [m["mountpoint"] for m in data["mountpoints"]]
        assert "BASE1" in names

    async def test_remote_mountpoints_bad_port(self):
        app = _app()
        code, _ = await _get(app, "/api/remote-mountpoints", {"host": "h", "port": 99999})
        assert code == 400

    async def test_remote_mountpoints_unreachable(self, monkeypatch):
        async def boom(host, port, timeout=10.0):
            raise OSError("connection refused")

        monkeypatch.setattr(geo, "fetch_sourcetable", boom)
        app = _app()
        code, _ = await _get(app, "/api/remote-mountpoints", {"host": "h", "port": 2101})
        assert code == 502

    async def test_remote_mountpoints_httpx_error(self, monkeypatch):
        import httpx

        async def boom(host, port, timeout=10.0):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(geo, "fetch_sourcetable", boom)
        app = _app()
        code, _ = await _get(app, "/api/remote-mountpoints", {"host": "h", "port": 2101})
        assert code == 502

    async def test_remote_station_unreachable(self, monkeypatch):
        async def boom(host, port, mp, user="", password="", timeout=15.0):
            raise OSError("connection refused")

        monkeypatch.setattr(geo, "fetch_station_coords", boom)
        app = _app()
        code, _ = await _get(
            app,
            "/api/remote-station",
            {"host": "h", "port": 2101, "mountpoint": "X", "user": "u", "password": "p"},
        )
        assert code == 502

    async def test_remote_station_timeout(self, monkeypatch):
        async def boom(host, port, mp, user="", password="", timeout=15.0):
            raise TimeoutError()

        monkeypatch.setattr(geo, "fetch_station_coords", boom)
        app = _app()
        code, _ = await _get(
            app,
            "/api/remote-station",
            {"host": "h", "port": 2101, "mountpoint": "X", "user": "u", "password": "p"},
        )
        assert code == 504

    async def test_remote_station_found(self, monkeypatch):
        async def fake_coords(host, port, mp, user="", password="", timeout=15.0):
            return {"latitude": LAT, "longitude": LON, "height": H}

        monkeypatch.setattr(geo, "fetch_station_coords", fake_coords)
        app = _app()
        code, data = await _get(
            app,
            "/api/remote-station",
            {"host": "h", "port": 2101, "mountpoint": "BASE1", "user": "u", "password": "p"},
        )
        assert code == 200
        assert data["found"] is True
        assert data["latitude"] == pytest.approx(LAT, abs=1e-5)
        assert data["ecef"] is not None

    async def test_remote_station_not_found(self, monkeypatch):
        async def none_coords(host, port, mp, user="", password="", timeout=15.0):
            return None

        monkeypatch.setattr(geo, "fetch_station_coords", none_coords)
        app = _app()
        code, data = await _get(
            app,
            "/api/remote-station",
            {"host": "h", "port": 2101, "mountpoint": "X", "user": "u", "password": "p"},
        )
        assert code == 200
        assert data["found"] is False

    async def test_remote_station_empty_mp(self):
        app = _app()
        code, _ = await _get(
            app,
            "/api/remote-station",
            {"host": "h", "port": 2101, "mountpoint": "", "user": "u", "password": "p"},
        )
        assert code == 400
