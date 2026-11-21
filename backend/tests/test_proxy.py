"""Тесты T-008: подмена координат (proxy).

Проверяются:
- трансформация RTCM 1005/1006 (absolute / offset) и потоковая буферизация
- CRUD API (list, create, delete, права, квота)
- relay: проверка upstream
- sourcetable включает SHIFTED/RELAY mountpoints
- закрытие клиентов SHIFTED при отключении источника
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import MagicMock

import bcrypt
import pyrtcm
import pytest
from app.api import proxy as proxy_api
from app.core.security import create_access_token
from app.db.models import Base, SourceModel, UserModel
from app.db.session import get_session as _orig_get_session
from app.gnss.parsers import crc24q, parse_rtcm3
from app.ntrip.hub import NtripHub
from app.services.proxy_service import ProxyService
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

LAT, LON, H = 55.7558, 37.6173, 200.0


# ---------- RTCM-хелперы (раскладка pyrtcm, как в test_geo) ----------


def _bits_uint(val: int, n: int) -> str:
    return format(val & ((1 << n) - 1), f"0{n}b")


def _bits_int(val: int, n: int) -> str:
    if val < 0:
        val += 1 << n
    return format(val, f"0{n}b")


def _build_arp(
    mid: int, x: float, y: float, z: float, station: int = 1234, ant: float | None = None
) -> bytes:
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


def _frame(payload: bytes) -> bytes:
    length = len(payload)
    header = bytes([0xD3, (length >> 8) & 0xFF, length & 0xFF])
    crc = crc24q(header + payload)
    return header + payload + bytes([crc >> 16, (crc >> 8) & 0xFF, crc & 0xFF])


def _ecef() -> tuple[float, float, float]:
    x, y, z = pyrtcm.llh2ecef(LAT, LON, H)
    return x, y, z


def _arp_frame(mid: int = 1005, ant: float | None = None) -> bytes:
    x, y, z = _ecef()
    return _frame(_build_arp(mid, x, y, z, station=777, ant=ant))


def _proxy(**kw) -> dict:
    base = {
        "id": "p1",
        "owner_id": "u1",
        "source_mountpoint": "BASE1",
        "target_mountpoint": "BASE1_SHIFTED",
        "mode": "absolute",
        "x": None,
        "y": None,
        "z": None,
        "de": None,
        "dn": None,
        "du": None,
        "is_active": True,
    }
    base.update(kw)
    return base


# ---------- трансформация RTCM ----------


class TestTransformRtcm:
    def test_absolute_1005(self):
        x, y, z = _ecef()
        original = _arp_frame(1005)
        proxy = _proxy(x=1000000.0, y=2000000.0, z=3000000.0)

        out = ProxyService.transform_rtcm(original, proxy)
        assert out != original

        frames = parse_rtcm3(out)
        assert len(frames) == 1
        assert frames[0].msg_type == 1005
        assert frames[0].crc_ok
        msg = pyrtcm.RTCMMessage(frames[0].data)
        assert msg.DF025 == pytest.approx(1000000.0, abs=1e-3)
        assert msg.DF026 == pytest.approx(2000000.0, abs=1e-3)
        assert msg.DF027 == pytest.approx(3000000.0, abs=1e-3)
        # прочие поля не тронуты
        assert msg.DF003 == 777

    def test_absolute_1006_keeps_antenna(self):
        original = _arp_frame(1006, ant=1.5)
        proxy = _proxy(x=5000000.0, y=4000000.0, z=3000000.0)

        out = ProxyService.transform_rtcm(original, proxy)
        msg = pyrtcm.RTCMMessage(parse_rtcm3(out)[0].data)
        assert msg.DF025 == pytest.approx(5000000.0, abs=1e-3)
        assert msg.DF028 == pytest.approx(1.5, abs=1e-4)

    def test_offset(self):
        x, y, z = _ecef()
        original = _arp_frame(1005)
        proxy = _proxy(mode="offset", de=10.0, dn=20.0, du=5.0)

        out = ProxyService.transform_rtcm(original, proxy)
        msg = pyrtcm.RTCMMessage(parse_rtcm3(out)[0].data)
        assert msg.DF025 == pytest.approx(x + 10.0, abs=1e-3)
        assert msg.DF026 == pytest.approx(y + 20.0, abs=1e-3)
        assert msg.DF027 == pytest.approx(z + 5.0, abs=1e-3)

    def test_absolute_without_coords_unchanged(self):
        original = _arp_frame(1005)
        out = ProxyService.transform_rtcm(original, _proxy())
        assert out == original

    def test_relay_unchanged(self):
        original = _arp_frame(1005)
        assert ProxyService.transform_rtcm(original, _proxy(mode="relay")) == original

    def test_garbage_unchanged(self):
        data = b"\x00\x01\x02\x03\x04"
        assert ProxyService.transform_rtcm(data, _proxy(x=0.0, y=0.0, z=0.0)) == data

    def test_non_arp_frames_preserved(self):
        """Кадры не 1005/1006 проходят без изменений (CRC сохраняется)."""
        arp = _arp_frame(1005)
        # 1074 = 0x432 -> первый байт 0x43, старшие 4 бита второго 0x2
        other = _frame(bytes([0x43, 0x20, 0x11, 0x22, 0x33, 0x44, 0x55]))
        data = arp + other
        proxy = _proxy(x=999999.0, y=888888.0, z=777777.0)

        out = ProxyService.transform_rtcm(data, proxy)
        frames = parse_rtcm3(out)
        assert [f.msg_type for f in frames] == [1005, 1074]
        assert all(f.crc_ok for f in frames)
        assert pyrtcm.RTCMMessage(frames[0].data).DF025 == pytest.approx(999999.0, abs=1e-3)
        assert frames[1].data == other[3:-3]


class TestStreamBuffering:
    def test_split_frame_reassembled(self):
        """Кадр, разрезанный границей чанка, собирается из буфера."""
        ps = ProxyService()
        full = _arp_frame(1005)
        half = len(full) // 2
        proxy = _proxy(x=1000000.0, y=2000000.0, z=3000000.0)

        first = ps.transform_chunk(proxy, full[:half])
        second = ps.transform_chunk(proxy, full[half:])
        assert first == b""  # кадр неполный — ничего не отдаём
        frames = parse_rtcm3(second)
        assert len(frames) == 1
        assert frames[0].crc_ok
        assert pyrtcm.RTCMMessage(frames[0].data).DF025 == pytest.approx(1000000.0, abs=1e-3)

    def test_whole_frame_passthrough(self):
        ps = ProxyService()
        full = _arp_frame(1005)
        proxy = _proxy(x=1000000.0, y=2000000.0, z=3000000.0)
        out = ps.transform_chunk(proxy, full)
        assert len(parse_rtcm3(out)) == 1


# ---------- ProxyService CRUD ----------


class TestProxyServiceCRUD:
    def test_add_get_delete(self):
        ps = ProxyService()
        ps.add_proxy("p1", "u1", "BASE1", "BASE1_SHIFTED", "absolute", x=1.0, y=2.0, z=3.0)
        assert ps.get_proxy("p1")["target_mountpoint"] == "BASE1_SHIFTED"
        assert ps.delete_proxy("p1") is not None
        assert ps.get_proxy("p1") is None
        assert ps.delete_proxy("p1") is None

    def test_by_owner(self):
        ps = ProxyService()
        ps.add_proxy("p1", "u1", "BASE1", "BASE1_SHIFTED", "absolute")
        ps.add_proxy("p2", "u1", "BASE2", "BASE2_SHIFTED", "offset")
        ps.add_proxy("p3", "u2", "BASE3", "BASE3_SHIFTED", "absolute")
        assert len(ps.get_proxies_by_owner("u1")) == 2

    def test_active_by_source(self):
        ps = ProxyService()
        ps.add_proxy("p1", "u1", "BASE1", "BASE1_SHIFTED", "absolute")
        ps.add_proxy("p2", "u1", "BASE1", "BASE1_RELAY", "relay")
        ps.add_proxy("p3", "u1", "BASE2", "BASE2_SHIFTED", "absolute")
        assert len(ps.get_active_by_source("BASE1")) == 2

    def test_deactivate_all(self):
        ps = ProxyService()
        ps.add_proxy("p1", "u1", "BASE1", "BASE1_SHIFTED", "absolute")
        ps.deactivate_all()
        assert ps.get_all_active() == []


# ---------- API ----------


PASSWORD = "longpassword123"


def _fast_hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=4)).decode()


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    s = sm()
    yield s
    await s.close()
    await engine.dispose()


@pytest.fixture
def hub() -> NtripHub:
    h = NtripHub()
    h.proxy_service = ProxyService()
    return h


@pytest.fixture
def app(session: AsyncSession, hub: NtripHub) -> FastAPI:
    application = FastAPI()
    application.include_router(proxy_api.router, prefix="/api/proxy")
    application.state.ctx = SimpleNamespace(
        ntrip_hub=hub,
        ntrip_server=SimpleNamespace(running=True),
        proxy_service=hub.proxy_service,
    )

    async def _override():
        yield session

    application.dependency_overrides[_orig_get_session] = _override
    return application


@pytest.fixture
def client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _make_user(
    session: AsyncSession,
    username: str = "testuser",
    role: str = "user",
    quotas_substitutions: int = 10,
) -> UserModel:
    u = UserModel(
        username=username,
        email=f"{username}@example.com",
        password_hash=_fast_hash(PASSWORD),
        role=role,
        status="approved",
        quotas_sources=10,
        quotas_substitutions=quotas_substitutions,
    )
    session.add(u)
    await session.commit()
    return u


async def _make_source(session: AsyncSession, owner: UserModel, mp: str = "BASE1") -> SourceModel:
    s = SourceModel(
        mountpoint=mp,
        password=_fast_hash(PASSWORD),
        owner_id=owner.id,
        is_active=True,
    )
    session.add(s)
    await session.commit()
    return s


def _auth(client: AsyncClient, username: str = "testuser") -> None:
    client.cookies.set("ntrip_session", create_access_token(username))


class TestProxyApi:
    async def test_requires_auth(self, client: AsyncClient):
        async with client as c:
            assert (await c.get("/api/proxy")).status_code == 401

    async def test_list_empty(self, client: AsyncClient, session: AsyncSession):
        await _make_user(session)
        _auth(client)
        async with client as c:
            resp = await c.get("/api/proxy")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_absolute(
        self, client: AsyncClient, session: AsyncSession, hub: NtripHub
    ):
        owner = await _make_user(session)
        await _make_source(session, owner)
        _auth(client)

        async with client as c:
            resp = await c.post(
                "/api/proxy",
                json={"mountpoint": "BASE1", "mode": "absolute", "x": 1.0, "y": 2.0, "z": 3.0},
            )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["mode"] == "absolute"
        assert data["source"] == "BASE1"
        assert data["mountpoint"] == "BASE1_SHIFTED"
        # сервис получил запись
        assert hub.proxy_service.get_proxy(data["id"]) is not None

    async def test_create_offset(self, client: AsyncClient, session: AsyncSession):
        owner = await _make_user(session)
        await _make_source(session, owner)
        _auth(client)

        async with client as c:
            resp = await c.post(
                "/api/proxy",
                json={"mountpoint": "BASE1", "mode": "offset", "de": 10.0, "dn": 20.0, "du": 5.0},
            )
        assert resp.status_code == 201
        assert resp.json()["de"] == 10.0

    async def test_create_relay(self, client: AsyncClient, session: AsyncSession, hub: NtripHub):
        owner = await _make_user(session)
        await _make_source(session, owner)
        _auth(client)

        async with client as c:
            resp = await c.post(
                "/api/proxy",
                json={
                    "mountpoint": "BASE1",
                    "mode": "relay",
                    "src_host": "127.0.0.1",
                    "src_port": 1,
                    "src_mountpoint": "UPSTREAM",
                    "src_user": "u",
                    "src_password": "p",
                },
            )
        assert resp.status_code == 201
        assert resp.json()["mountpoint"] == "BASE1_RELAY"
        # фоновая relay-задача не должна висеть после теста
        await hub.proxy_service.stop_relay("BASE1_RELAY")

    async def test_relay_missing_fields(self, client: AsyncClient, session: AsyncSession):
        owner = await _make_user(session)
        await _make_source(session, owner)
        _auth(client)

        async with client as c:
            resp = await c.post("/api/proxy", json={"mountpoint": "BASE1", "mode": "relay"})
        assert resp.status_code == 422

    async def test_source_not_found(self, client: AsyncClient, session: AsyncSession):
        await _make_user(session)
        _auth(client)

        async with client as c:
            resp = await c.post(
                "/api/proxy",
                json={"mountpoint": "NOPE", "mode": "absolute", "x": 1.0, "y": 2.0, "z": 3.0},
            )
        assert resp.status_code == 404

    async def test_quota_exceeded(self, client: AsyncClient, session: AsyncSession):
        owner = await _make_user(session, quotas_substitutions=0)
        await _make_source(session, owner)
        _auth(client)

        async with client as c:
            resp = await c.post(
                "/api/proxy",
                json={"mountpoint": "BASE1", "mode": "absolute", "x": 1.0, "y": 2.0, "z": 3.0},
            )
        assert resp.status_code == 403

    async def test_duplicate_target(self, client: AsyncClient, session: AsyncSession):
        owner = await _make_user(session)
        await _make_source(session, owner)
        _auth(client)
        payload = {"mountpoint": "BASE1", "mode": "absolute", "x": 1.0, "y": 2.0, "z": 3.0}

        async with client as c:
            assert (await c.post("/api/proxy", json=payload)).status_code == 201
            assert (await c.post("/api/proxy", json=payload)).status_code == 409

    async def test_delete(self, client: AsyncClient, session: AsyncSession):
        owner = await _make_user(session)
        await _make_source(session, owner)
        _auth(client)

        async with client as c:
            created = await c.post(
                "/api/proxy",
                json={"mountpoint": "BASE1", "mode": "absolute", "x": 1.0, "y": 2.0, "z": 3.0},
            )
            pid = created.json()["id"]
            resp = await c.delete(f"/api/proxy/{pid}")
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}
            assert (await c.delete(f"/api/proxy/{pid}")).status_code == 404

    async def test_foreign_source_forbidden(self, client: AsyncClient, session: AsyncSession):
        owner = await _make_user(session, username="owner")
        await _make_source(session, owner)
        await _make_user(session, username="other")
        _auth(client, "other")

        async with client as c:
            resp = await c.post(
                "/api/proxy",
                json={"mountpoint": "BASE1", "mode": "absolute", "x": 1.0, "y": 2.0, "z": 3.0},
            )
        assert resp.status_code == 403

    async def test_check_upstream_not_relay(self, client: AsyncClient, session: AsyncSession):
        owner = await _make_user(session)
        await _make_source(session, owner)
        _auth(client)

        async with client as c:
            created = await c.post(
                "/api/proxy",
                json={"mountpoint": "BASE1", "mode": "absolute", "x": 1.0, "y": 2.0, "z": 3.0},
            )
            pid = created.json()["id"]
            resp = await c.get(f"/api/proxy/{pid}/check-upstream")
        assert resp.status_code == 200
        assert resp.json()["ok"] is False

    async def test_check_upstream_unknown(self, client: AsyncClient, session: AsyncSession):
        await _make_user(session)
        _auth(client)
        async with client as c:
            resp = await c.get("/api/proxy/unknown/check-upstream")
        assert resp.status_code == 404


# ---------- relay upstream ----------


class TestCheckUpstream:
    async def test_unreachable(self):
        ps = ProxyService()
        result = await ps.check_upstream(
            _proxy(mode="relay", relay_host="127.0.0.1", relay_port=1, relay_mountpoint="X")
        )
        assert result["ok"] is False

    async def test_not_relay(self):
        result = await ProxyService().check_upstream(_proxy(mode="absolute"))
        assert result["ok"] is False
        assert "not relay" in result["error"]

    async def test_missing_fields(self):
        result = await ProxyService().check_upstream(_proxy(mode="relay"))
        assert result["ok"] is False


# ---------- hub ----------


class TestHubProxyIntegration:
    async def test_sourcetable_includes_targets(self, monkeypatch):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sm = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        monkeypatch.setattr("app.ntrip.hub.session_scope", sm)

        hub = NtripHub()
        hub.proxy_service = ProxyService()
        hub.proxy_service.add_proxy("p1", "u1", "BASE1", "BASE1_SHIFTED", "absolute")
        hub.proxy_service.add_proxy("p2", "u1", "BASE1", "BASE1_RELAY", "relay")

        mps = [s["mountpoint"] for s in await hub._get_active_sources()]
        assert "BASE1_SHIFTED" in mps
        assert "BASE1_RELAY" in mps
        await engine.dispose()

    async def test_cleanup_shifted_clients(self):
        hub = NtripHub()
        hub.proxy_service = ProxyService()
        hub.proxy_service.add_proxy("p1", "u1", "BASE1", "BASE1_SHIFTED", "absolute")
        hub.proxy_service.add_proxy("p2", "u1", "BASE1", "BASE1_RELAY", "relay")

        writer = MagicMock()
        writer.is_closing.return_value = False
        hub._client_sessions["BASE1_SHIFTED"] = [
            {
                "mountpoint": "BASE1_SHIFTED",
                "peer": "1.1.1.1:1",
                "writer": writer,
                "bytes_sent": 10,
                "conn": None,
            }
        ]
        relay_writer = MagicMock()
        relay_writer.is_closing.return_value = False
        hub._client_sessions["BASE1_RELAY"] = [
            {
                "mountpoint": "BASE1_RELAY",
                "peer": "2.2.2.2:2",
                "writer": relay_writer,
                "bytes_sent": 20,
                "conn": None,
            }
        ]

        await hub._cleanup_proxy_client_sessions("BASE1")

        # SHIFTED закрыт, RELAY (внешний поток) — нет
        assert "BASE1_SHIFTED" not in hub._client_sessions
        assert "BASE1_RELAY" in hub._client_sessions
        writer.close.assert_called_once()
