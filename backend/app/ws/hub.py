"""WebSocket-хаб: real-time push для дашборда."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger("rucaster.ws")


class WsHub:
    """Централизованный хаб WebSocket-подключений."""

    def __init__(self) -> None:
        self._clients: dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, username: str = "") -> None:
        await ws.accept()
        async with self._lock:
            self._clients[ws] = username
        log.info("WebSocket client connected: %s. Total: %d", username, len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.pop(ws, None)
        log.info("WebSocket client disconnected. Total: %d", len(self._clients))

    async def broadcast(self, data: dict) -> None:
        """Отправить сообщение всем подключённым клиентам (текстовый JSON-кадр)."""
        payload = json.dumps(data, default=str)
        async with self._lock:
            disconnected = []
            for ws in self._clients:
                try:
                    await ws.send_text(payload)
                except (WebSocketDisconnect, RuntimeError):
                    disconnected.append(ws)
            for ws in disconnected:
                self._clients.pop(ws, None)

    async def send_to(self, ws: WebSocket, data: dict) -> None:
        """Отправить сообщение конкретному клиенту."""
        try:
            await ws.send_json(data)
        except (WebSocketDisconnect, RuntimeError):
            pass

    @property
    def client_count(self) -> int:
        return len(self._clients)


# Глобальный экземпляр
ws_hub = WsHub()
