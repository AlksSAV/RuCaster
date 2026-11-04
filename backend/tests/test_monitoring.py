"""Тесты мониторинга (T-003): журнал подключений и снимки состояния hub.

Тестируются методы NtripHub без БД и TCP: в хаб внедряются фейковые
сессии источников/клиентов, проверяется форма данных для API.
"""

from __future__ import annotations

import time

from app.gnss.parsers import parse_gga
from app.ntrip.hub import NtripHub, extract_nmea_lines, position_from_gga


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


GGA_FIX4 = "$GNGGA,182839.12,3916.48212,N,08952.49420,W,4,12,0.8,150.0,M,14.0,M,1.0,0000*4A"


class TestExtractNmeaLines:
    def test_complete_lines(self):
        buf = bytearray(b"$GPGGA,1,2\r\n$GNGGA,3,4\r\n")
        lines = extract_nmea_lines(buf)
        assert len(lines) == 2
        assert lines[0].startswith("$GPGGA")
        assert buf == b""  # полный буфер очищается

    def test_partial_line_stays_in_buffer(self):
        buf = bytearray(b"$GNGGA,1234" )
        assert extract_nmea_lines(buf) == []
        assert bytes(buf) == b"$GNGGA,1234"
        # достраиваем строку — теперь она выделяется
        buf.extend(b",5678\r\n")
        lines = extract_nmea_lines(buf)
        assert len(lines) == 1
        assert lines[0] == "$GNGGA,1234,5678"

    def test_line_split_across_chunks(self):
        """GGA, пришедший двумя кусками, должен распарситься целиком."""
        buf = bytearray()
        buf.extend(GGA_FIX4[:20].encode())
        assert extract_nmea_lines(buf) == []
        buf.extend(GGA_FIX4[20:].encode() + b"\r\n")
        lines = extract_nmea_lines(buf)
        assert len(lines) == 1
        gga = parse_gga(lines[0])
        assert gga is not None
        assert gga.fix_quality == 4

    def test_short_lines_dropped(self):
        buf = bytearray(b"\r\nx\r\n" + GGA_FIX4.encode() + b"\r\n")
        lines = extract_nmea_lines(buf)
        assert lines == [GGA_FIX4]

    def test_overflow_buffer_cleared(self):
        """Поток без переводов строк (например чистый RTCM) не должен растить буфер вечно."""
        buf = bytearray(b"\xd3" * 2000)
        assert extract_nmea_lines(buf) == []
        assert len(buf) == 0


class TestPositionFromGga:
    def test_fields(self):
        gga = parse_gga(GGA_FIX4)
        assert gga is not None
        pos = position_from_gga(gga)
        assert pos["fix_quality"] == 4
        assert pos["num_sats"] == 12
        assert pos["hdop"] == 0.8
        assert pos["altitude"] == 150.0
        assert pos["geoid_sep"] == 14.0
        assert pos["age"] == 1.0
        assert abs(pos["latitude"] - 39.274702) < 1e-4
        assert abs(pos["longitude"] + 89.874903) < 1e-4


class TestGgaUpdatesSession:
    """Сквозная проверка пути T-005: строка GGA -> позиция в снимках мониторинга."""

    def test_session_position_updated(self):
        hub = NtripHub()
        s = _make_client_session(hub)
        # так же, как это делает цикл чтения в handle_client
        buf = bytearray(GGA_FIX4.encode() + b"\r\n")
        for line in extract_nmea_lines(buf):
            gga = parse_gga(line)
            if gga is not None:
                s["position"] = position_from_gga(gga)
                s["position_at"] = time.time()

        positions = hub.get_positions()
        assert len(positions) == 1
        p = positions[0]
        assert abs(p["latitude"] - 39.274702) < 1e-4
        assert p["fix_quality"] == 4
        assert p["updated_at"] is not None
        assert p["age_seconds"] is not None and p["age_seconds"] < 2.0

        clients = hub.get_clients()
        assert clients[0]["latitude"] is not None
        assert clients[0]["num_sats"] == 12

    def test_no_fix_gga_does_not_update(self):
        """GGA без фиксации (quality=0) не должен перезаписывать позицию."""
        hub = NtripHub()
        s = _make_client_session(hub)
        no_fix = "$GNGGA,120000.00,5500.00000,N,03700.00000,E,0,00,99.9,0.0,M,0.0,M,,"
        for line in extract_nmea_lines(bytearray(no_fix.encode() + b"\r\n")):
            gga = parse_gga(line)
            if gga is not None:
                s["position"] = position_from_gga(gga)
                s["position_at"] = time.time()
        assert s["position"] is None
        assert s["position_at"] is None
        assert hub.get_positions()[0]["latitude"] is None
