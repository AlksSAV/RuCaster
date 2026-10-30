"""Тесты HTTP-эндпоинтов мониторинга (T-003).

Проверяется обвязка API: hub внедряется через app.state.ctx (как в main.py),
запросы идут через ASGI-транспорт без реального NTRIP-сервера и БД.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from app.api import monitoring
from app.ntrip.hub import NtripHub
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


class _FakeServer:
    running = True


def _make_app(hub: NtripHub) -> FastAPI:
    app = FastAPI()
    app.include_router(monitoring.router)
    app.state.ctx = SimpleNamespace(ntrip_hub=hub, ntrip_server=_FakeServer())
    return app


def _make_client_session(hub: NtripHub, mountpoint: str = "BASE1") -> dict:
    session = {
        "mountpoint": mountpoint,
        "user": "rover1",
        "peer": "10.0.0.5:55000",
        "user_agent": None,
        "connected_at": time.time() - 5.0,
        "writer": None,
        "bytes_sent": 0,
        "conn": hub._log_connection("client", mountpoint, "10.0.0.5"),
        "position": None,
        "position_at": None,
    }
    hub._client_sessions.setdefault(mountpoint, []).append(session)
    hub._total_client_connections += 1
    return session


@pytest.fixture
def hub() -> NtripHub:
    return NtripHub()


@pytest.fixture
def client(hub: NtripHub) -> AsyncClient:
    app = _make_app(hub)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_status_not_stub(client: AsyncClient):
    """/status больше не заглушка: ответ либо валидный, либо ошибка БД, но не пустой OFFLINE."""
    resp = await client.get("/status")
    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        data = resp.json()
        assert "sources" in data
        assert "total_clients" in data


async def test_clients_endpoint(client: AsyncClient, hub: NtripHub):
    _make_client_session(hub)
    resp = await client.get("/clients")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["mountpoint"] == "BASE1"
    assert data[0]["ip"] == "10.0.0.5:55000"
    assert data[0]["latitude"] is None


async def test_positions_endpoint(client: AsyncClient, hub: NtripHub):
    _make_client_session(hub)
    resp = await client.get("/positions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["updated_at"] is None  # GGA ещё не парсится (T-005)


async def test_positions_with_data(client: AsyncClient, hub: NtripHub):
    s = _make_client_session(hub)
    s["position"] = {
        "latitude": 55.75,
        "longitude": 37.62,
        "fix_quality": 4,
        "num_sats": 10,
        "hdop": 1.1,
        "altitude": 140.0,
        "geoid_sep": 13.5,
        "age": 2.0,
    }
    s["position_at"] = time.time() - 1.0
    resp = await client.get("/positions")
    data = resp.json()
    assert data[0]["latitude"] == 55.75
    assert data[0]["fix_quality"] == 4
    assert data[0]["updated_at"] is not None


async def test_connections_endpoint(client: AsyncClient, hub: NtripHub):
    _make_client_session(hub)
    hub._log_connection("source", "BASE1", "10.0.0.9")
    resp = await client.get("/connections?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["type"] == "source"  # свежие первыми
    assert data[0]["disconnected_at"] is None


async def test_statistics_endpoint_is_real_not_stub(client: AsyncClient):
    """/statistics больше не заглушка 501: обращается к БД и возвращает валидный JSON."""
    resp = await client.get("/statistics")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_sources" in data
    assert "active_clients" in data
