"""Тесты NTRIP server: парсинг basic-auth, сборка sourcetable, диспетчер TCP.

Без реального железа и внешних кастеров: используется asyncio StreamReader с
предзаполненным буфером и фейковый StreamWriter.
"""

from __future__ import annotations

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock

from app.ntrip.server import (
    AUTH_REQUIRED,
    NtripServer,
    build_sourcetable,
    parse_basic_auth,
)


def _make_reader(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


class _FakeWriter:
    """Минимальный StreamWriter: буфер записанных байтов + close/drain."""

    def __init__(self, peer: tuple | None = ("10.0.0.1", 5000)) -> None:
        self.buffer = bytearray()
        self.closed = False
        self._peer = peer

    def get_extra_info(self, name: str):
        assert name == "peername"
        return self._peer

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


# ---------- parse_basic_auth ----------


class TestParseBasicAuth:
    def test_valid(self):
        header = "Basic " + base64.b64encode(b"user:pass").decode()
        assert parse_basic_auth(header) == ("user", "pass")

    def test_empty_password(self):
        header = "Basic " + base64.b64encode(b"user:").decode()
        assert parse_basic_auth(header) == ("user", "")

    def test_case_insensitive_prefix(self):
        header = "basic " + base64.b64encode(b"u:p").decode()
        assert parse_basic_auth(header) == ("u", "p")

    def test_no_colon(self):
        header = "Basic " + base64.b64encode(b"nocolon").decode()
        assert parse_basic_auth(header) is None

    def test_wrong_scheme(self):
        assert parse_basic_auth("Bearer token123") is None
        assert parse_basic_auth("") is None

    def test_invalid_b64(self):
        assert parse_basic_auth("Basic !!!not-base64!!!") is None


# ---------- build_sourcetable ----------


class TestBuildSourcetable:
    def test_empty(self):
        result = build_sourcetable([])
        assert result.startswith("SOURCETABLE 200 OK")
        assert "ENDSOURCETABLE" in result
        assert "STR;" not in result

    def test_single_entry(self):
        result = build_sourcetable([
            {
                "mountpoint": "BASE1",
                "identifier": "My Base",
                "format": "RTCM 3",
                "nav_system": "GPS",
                "latitude": "55.75",
                "longitude": "37.62",
            }
        ])
        assert "STR;BASE1;My Base;RTCM 3;0;GPS;" in result
        assert ";55.75;37.62;" in result

    def test_defaults_missing_fields(self):
        result = build_sourcetable([{"mountpoint": "X"}])
        assert "STR;X;X;RTCM 3;" in result
        assert "GPS+GLO+GAL+BDS" in result

    def test_line_endings(self):
        result = build_sourcetable([{"mountpoint": "A"}])
        assert result.endswith("\r\n")
        assert "\r\nSTR;A;" in result


# ---------- NtripServer._handle_client / _dispatch ----------


class TestServerDispatch:
    async def test_sourcetable_root(self):
        hub = MagicMock()
        hub.handle_sourcetable = AsyncMock()
        server = NtripServer(hub)
        reader = _make_reader(b"GET / HTTP/1.1\r\n\r\n")
        writer = _FakeWriter()

        await server._handle_client(reader, writer)

        hub.handle_sourcetable.assert_called_once()
        headers = hub.handle_sourcetable.call_args[0][0]
        assert isinstance(headers, dict)

    async def test_sourcetable_streams(self):
        hub = MagicMock()
        hub.handle_sourcetable = AsyncMock()
        server = NtripServer(hub)
        reader = _make_reader(b"GET /streams HTTP/1.0\r\n\r\n")
        writer = _FakeWriter()

        await server._handle_client(reader, writer)
        hub.handle_sourcetable.assert_called_once()

    async def test_source(self):
        hub = MagicMock()
        hub.handle_source = AsyncMock()
        server = NtripServer(hub)
        reader = _make_reader(b"SOURCE pass123 /BASE1 HTTP/1.0\r\n\r\n")
        writer = _FakeWriter(peer=("10.0.0.1", 54321))

        await server._handle_client(reader, writer)

        hub.handle_source.assert_called_once()
        args = hub.handle_source.call_args[0]
        assert args[0] == "BASE1"
        assert args[1] == "pass123"
        assert args[4] == "10.0.0.1:54321"

    async def test_client_stream(self):
        hub = MagicMock()
        hub.handle_client = AsyncMock()
        server = NtripServer(hub)
        auth = base64.b64encode(b"rover:secret").decode()
        raw = f"GET /BASE1 HTTP/1.0\r\nAuthorization: Basic {auth}\r\nUser-Agent: test\r\n\r\n"
        reader = _make_reader(raw.encode())
        writer = _FakeWriter(peer=("10.0.0.2", 55555))

        await server._handle_client(reader, writer)

        hub.handle_client.assert_called_once()
        args = hub.handle_client.call_args[0]
        assert args[0] == "BASE1"  # mountpoint без ведущего слэша
        headers = args[1]
        assert "authorization" in headers
        assert headers["user-agent"] == "test"

    async def test_unknown_method_401(self):
        hub = MagicMock()
        server = NtripServer(hub)
        reader = _make_reader(b"POST /foo HTTP/1.0\r\n\r\n")
        writer = _FakeWriter()

        await server._handle_client(reader, writer)

        assert AUTH_REQUIRED.encode() in bytes(writer.buffer)

    async def test_malformed_request_line_401(self):
        hub = MagicMock()
        server = NtripServer(hub)
        reader = _make_reader(b"BADREQUEST\r\n\r\n")
        writer = _FakeWriter()

        await server._handle_client(reader, writer)
        assert AUTH_REQUIRED.encode() in bytes(writer.buffer)

    async def test_empty_request_closes_quietly(self):
        hub = MagicMock()
        server = NtripServer(hub)
        reader = _make_reader(b"")
        writer = _FakeWriter()

        await server._handle_client(reader, writer)
        assert bytes(writer.buffer) == b""
        assert writer.closed

    async def test_source_without_mountpoint(self):
        hub = MagicMock()
        hub.handle_source = AsyncMock()
        server = NtripServer(hub)
        # "SOURCE pass123" + лишнее — parts[1] = pass, mp = parts[2] lstrip('/')
        reader = _make_reader(b"SOURCE pass123 / HTTP/1.0\r\n\r\n")
        writer = _FakeWriter()

        await server._handle_client(reader, writer)
        args = hub.handle_source.call_args[0]
        assert args[0] == ""  # '/' -> lstrip -> ''

    async def test_active_connections_decremented(self):
        hub = MagicMock()
        hub.handle_sourcetable = AsyncMock()
        server = NtripServer(hub)
        reader = _make_reader(b"GET / HTTP/1.0\r\n\r\n")
        writer = _FakeWriter()

        assert server.active_connections == 0
        await server._handle_client(reader, writer)
        assert server.active_connections == 0  # инкремент парится декрементом в finally
