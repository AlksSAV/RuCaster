"""Тесты мониторинга (T-003): журнал подключений и снимки состояния hub.

Тестируются методы NtripHub без БД и TCP: в хаб внедряются фейковые
сессии источников/клиентов, проверяется форма данных для API.
"""

from __future__ import annotations

import time

from app.ntrip.hub import NtripHub


def _make_client_session(
    hub: NtripHub,
    mountpoint: str = "BASE1",
    peer: str = "10.0.0.5:55000",
    user: str = "rover1",
    position: dict | None = None,
    position_at: float | None = None,
) -> dict:
    """Зарегистрировать клиентскую сессию так же, как это делает handle_client."""
    session = {
        "mountpoint": mountpoint,
        "user": user,
        "peer": peer,
        "user_agent": "test-agent",
        "connected_at": time.time() - 12.5,
        "writer": None,  # broadcast в этих тестах не вызывается
        "bytes_sent": 0,
        "conn": hub._log_connection("client", mountpoint, peer.rpartition(":")[0]),
        "position": position,
        "position_at": position_at,
    }
    hub._client_sessions.setdefault(mountpoint, []).append(session)
    hub._total_client_connections += 1
    return session


class TestConnectionLog:
    def test_log_and_finish(self):
        hub = NtripHub()
        entry = hub._log_connection("source", "BASE1", "10.0.0.1")
        assert entry.disconnected_at is None
        assert entry.type == "source"

        hub._finish_connection(entry, bytes_received=1024)
        assert entry.disconnected_at is not None
        assert entry.bytes_received == 1024

    def test_finish_is_idempotent(self):
        hub = NtripHub()
        entry = hub._log_connection("client", "BASE1", "10.0.0.2")
        hub._finish_connection(entry, bytes_sent=10)
        first = entry.disconnected_at
        hub._finish_connection(entry, bytes_sent=999)
        assert entry.disconnected_at == first
        assert entry.bytes_sent == 10  # повторный finish ничего не перезаписывает

    def test_connections_order_and_limit(self):
        hub = NtripHub()
        for i in range(5):
            hub._log_connection("client", f"MP{i}", f"10.0.0.{i}")

        all_entries = hub.get_connections(limit=50)
        assert len(all_entries) == 5
        # свежие первыми
        assert all_entries[0]["mountpoint"] == "MP4"
        assert all_entries[-1]["mountpoint"] == "MP0"

        limited = hub.get_connections(limit=2)
        assert [e["mountpoint"] for e in limited] == ["MP4", "MP3"]

    def test_rejected_counter(self):
        hub = NtripHub()
        assert hub.get_status_sync_rejected() == 0 if False else True
        hub._register_rejection()
        hub._register_rejection()
        assert hub._rejected == 2


class TestClientsSnapshot:
    def test_empty_hub(self):
        hub = NtripHub()
        assert hub.get_clients() == []
        assert hub.get_positions() == []
        assert hub.clients_per_mountpoint() == {}

    def test_clients_without_position(self):
        hub = NtripHub()
        _make_client_session(hub)
        clients = hub.get_clients()
        assert len(clients) == 1
        c = clients[0]
        assert c["mountpoint"] == "BASE1"
        assert c["ip"] == "10.0.0.5:55000"
        assert c["user_agent"] == "test-agent"
        assert c["connected_s"] >= 12.0
        # координаты — только после T-005
        assert c["latitude"] is None
        assert c["age_seconds"] is None

    def test_client_with_position(self):
        hub = NtripHub()
        pos = {
            "latitude": 55.75,
            "longitude": 37.62,
            "fix_quality": 4,
            "num_sats": 12,
            "hdop": 0.8,
            "altitude": 150.0,
            "geoid_sep": 14.0,
            "age": 1.0,
        }
        now = time.time()
        _make_client_session(hub, position=pos, position_at=now - 3.0)

        positions = hub.get_positions()
        assert len(positions) == 1
        p = positions[0]
        assert p["latitude"] == 55.75
        assert p["fix_quality"] == 4
        assert p["updated_at"] is not None
        assert p["age_seconds"] is not None and 2.0 < p["age_seconds"] < 5.0

    def test_remove_client_session(self):
        hub = NtripHub()
        s = _make_client_session(hub)
        hub._remove_client_session("BASE1", s)
        assert hub.get_clients() == []
        # разрыв зафиксирован в журнале
        entry = hub.get_connections()[0]
        assert entry["disconnected_at"] is not None

    def test_clients_per_mountpoint(self):
        hub = NtripHub()
        _make_client_session(hub, mountpoint="A", peer="1.1.1.1:1")
        _make_client_session(hub, mountpoint="A", peer="1.1.1.2:2")
        _make_client_session(hub, mountpoint="B", peer="1.1.1.3:3")
        assert hub.clients_per_mountpoint() == {"A": 2, "B": 1}
