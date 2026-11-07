"""Тесты T-006: WebSocket push-события из NtripHub в ws_hub.

Проверяется:
- WsHub: рассылка текстовых JSON-кадров, удаление отвалившихся клиентов
- hub._emit доставляет события в подменённый ws_hub
"""

from __future__ import annotations

import json
from collections import deque
from unittest.mock import patch

from app.ntrip.hub import NtripHub
from app.ws.hub import WsHub

# ---------- helpers ----------


class _FakeWs:
    """Фейковый WebSocket, собирающий отправленные текстовые кадры."""

    def __init__(self) -> None:
        self.messages: deque[str] = deque()

    async def send_text(self, text: str) -> None:
        self.messages.append(text)


class _BrokenWs:
    """WS, который падает при отправке (эмуляция разорванного соединения)."""

    async def send_text(self, text: str) -> None:
        raise RuntimeError("broken")


# ---------- WsHub ----------


class TestWsHubBroadcast:
    async def test_broadcast_delivers_to_all(self):
        ws1, ws2 = _FakeWs(), _FakeWs()
        hub = WsHub()
        hub._clients = {ws1: "u1", ws2: "u2"}

        await hub.broadcast({"type": "test", "data": {"x": 1}})

        for ws in (ws1, ws2):
            assert len(ws.messages) == 1
            msg = json.loads(ws.messages[0])
            assert msg["type"] == "test"
            assert msg["data"]["x"] == 1

    async def test_broadcast_removes_broken_ws(self):
        good = _FakeWs()
        hub = WsHub()
        hub._clients = {_BrokenWs(): "broken", good: "good"}

        await hub.broadcast({"type": "test", "data": {}})

        assert good in hub._clients
        assert hub.client_count == 1

    async def test_disconnect_removes_client(self):
        ws = _FakeWs()
        hub = WsHub()
        hub._clients = {ws: "u1"}

        await hub.disconnect(ws)

        assert ws not in hub._clients
        assert hub.client_count == 0


# ---------- NtripHub._emit ----------


class TestHubEmit:
    async def test_emit_delivers_event(self):
        hub = NtripHub()
        ws = _FakeWs()
        test_ws_hub = WsHub()
        test_ws_hub._clients = {ws: "test"}

        with patch("app.ntrip.hub.ws_hub", test_ws_hub):
            await hub._emit("source_connected", {"mountpoint": "BASE1", "peer": "10.0.0.1"})

        msg = json.loads(ws.messages[0])
        assert msg["type"] == "source_connected"
        assert msg["data"]["mountpoint"] == "BASE1"
        assert msg["data"]["peer"] == "10.0.0.1"

    async def test_emit_all_event_types(self):
        hub = NtripHub()
        ws = _FakeWs()
        test_ws_hub = WsHub()
        test_ws_hub._clients = {ws: "test"}

        events = [
            ("source_disconnected", {"mountpoint": "B", "peer": "p", "bytes_received": 1024}),
            ("client_connected", {"mountpoint": "B", "user": "r1", "peer": "p"}),
            ("client_disconnected", {"mountpoint": "B", "user": "r1", "peer": "p", "bytes_sent": 2048}),
        ]
        with patch("app.ntrip.hub.ws_hub", test_ws_hub):
            for type_, data in events:
                await hub._emit(type_, data)

        types = [json.loads(m)["type"] for m in ws.messages]
        assert types == [e[0] for e in events]

    async def test_emit_no_ws_clients_is_noop(self):
        """Если нет WS-клиентов — _emit не падает (broadcast по пустому списку)."""
        hub = NtripHub()
        empty_ws_hub = WsHub()

        with patch("app.ntrip.hub.ws_hub", empty_ws_hub):
            await hub._emit("source_connected", {"mountpoint": "BASE1", "peer": "10.0.0.1"})

    async def test_emit_swallows_broadcast_errors(self):
        """Сбой WS не должен влиять на NTRIP-сессии: _emit глотает исключения."""
        hub = NtripHub()
        hub_ws = WsHub()

        class _Boom:
            async def send_text(self, text: str) -> None:
                raise RuntimeError("ws down")

        # _Boom не WebSocket — broadcast не поймает RuntimeError в свой except
        # по типу, но сам _emit обязан вернуть управление без исключения.
        # Эмулируем падение самого broadcast:
        async def _boom_broadcast(data):
            raise RuntimeError("ws down")

        hub_ws.broadcast = _boom_broadcast  # type: ignore[method-assign]
        with patch("app.ntrip.hub.ws_hub", hub_ws):
            await hub._emit("source_connected", {"mountpoint": "BASE1"})  # no raise
