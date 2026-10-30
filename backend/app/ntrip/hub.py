"""Hub — централизованное управление сессиями NTRIP и состоянием для мониторинга."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.security import verify_password
from app.db.models import SourceModel, UserModel
from app.db.session import session_scope
from app.ntrip.server import (
    AUTH_REQUIRED,
    NTRIP_OK,
    SOURCE_OK,
    SOURCE_UNAUTHORIZED,
    build_sourcetable,
)

log = logging.getLogger("rucaster.ntrip")

# Максимальное число записей в кольцевом журнале подключений
_CONNECTION_LOG_SIZE = 200


class ConnectionEntry:
    """Запись кольцевого журнала подключений."""

    __slots__ = (
        "id",
        "type",
        "mountpoint",
        "ip_address",
        "connected_at",
        "disconnected_at",
        "bytes_sent",
        "bytes_received",
    )

    def __init__(self, type: str, mountpoint: str | None, ip_address: str) -> None:
        self.id = str(uuid.uuid4())
        self.type = type
        self.mountpoint = mountpoint
        self.ip_address = ip_address
        self.connected_at = datetime.now(UTC)
        self.disconnected_at: datetime | None = None
        self.bytes_sent = 0
        self.bytes_received = 0


def _peer_ip(peer: str) -> str:
    """IP из 'host:port' (работает и для IPv6-хоста, и для 'unknown')."""
    if peer == "unknown":
        return peer
    head, sep, tail = peer.rpartition(":")
    return head if sep and tail.isdigit() else peer


class NtripHub:
    """Хаб: активные сессии источников/клиентов, журнал подключений, снимки для API."""

    def __init__(self) -> None:
        self._source_sessions: dict[str, dict] = {}
        self._client_sessions: dict[str, list[dict]] = {}
        self._connections: deque[ConnectionEntry] = deque(maxlen=_CONNECTION_LOG_SIZE)
        self._rejected = 0
        # Накопительные счётчики (не зависят от размера кольцевого журнала)
        self._total_client_connections = 0

    # ---------- учёт в журнале ----------

    def _log_connection(
        self, type: str, mountpoint: str | None, ip_address: str
    ) -> ConnectionEntry:
        entry = ConnectionEntry(type=type, mountpoint=mountpoint, ip_address=ip_address)
        self._connections.append(entry)
        return entry

    @staticmethod
    def _finish_connection(
        entry: ConnectionEntry | None, bytes_sent: int = 0, bytes_received: int = 0
    ) -> None:
        if entry is None or entry.disconnected_at is not None:
            return
        entry.disconnected_at = datetime.now(UTC)
        entry.bytes_sent = bytes_sent
        entry.bytes_received = bytes_received

    def _register_rejection(self) -> None:
        self._rejected += 1

    # ---------- NTRIP: sourcetable ----------

    async def handle_sourcetable(
        self, headers: dict[str, str], writer: asyncio.StreamWriter
    ) -> None:
        """Обработка запроса SOURCETABLE."""
        is_ntrip2 = headers.get("ntrip-version", "").startswith("Ntrip/2.0")

        if is_ntrip2:
            body_bytes = build_sourcetable(await self._get_active_sources()).encode("utf-8")
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Server: NTRIP RuCaster/1.0\r\n"
                "Content-Type: gnss/sourcetable\r\n"
                f"Content-Length: {len(body_bytes)}\r\n"
                "Connection: close\r\n\r\n"
            )
            writer.write(response.encode() + body_bytes)
        else:
            body = build_sourcetable(await self._get_active_sources())
            writer.write(("HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n" + body).encode())

        await writer.drain()
        writer.close()
        await writer.wait_closed()

    # ---------- NTRIP: источник (база) ----------

    async def handle_source(
        self,
        mountpoint: str,
        password: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        peer: str,
    ) -> None:
        """Обработка входящего подключения от источника (базы): SOURCE <pass> /<mp>."""
        async with session_scope() as session:
            stmt = select(SourceModel).where(SourceModel.mountpoint == mountpoint)
            source = (await session.execute(stmt)).scalar_one_or_none()

        if not source or not verify_password(password, source.password):
            self._register_rejection()
            writer.write(SOURCE_UNAUTHORIZED.encode())
            await writer.drain()
            writer.close()
            return

        writer.write(SOURCE_OK.encode())
        await writer.drain()

        session_id = f"{mountpoint}:{peer}"
        now = datetime.now(UTC)
        self._source_sessions[session_id] = {
            "mountpoint": mountpoint,
            "peer": peer,
            "connected_at": now,
            "last_seen": now,
            "bytes_received": 0,
            "reader": reader,
            "writer": writer,
            "conn": self._log_connection("source", mountpoint, _peer_ip(peer)),
        }

        log.info("Source connected: %s from %s", mountpoint, peer)
        await self._read_source_stream(session_id, mountpoint, reader)

    async def _read_source_stream(
        self, session_id: str, mountpoint: str, reader: asyncio.StreamReader
    ) -> None:
        """Читать поток базы, ретранслировать клиентам и держать журнал."""
        session = self._source_sessions.get(session_id)
        if not session:
            return

        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                session["bytes_received"] += len(data)
                session["last_seen"] = datetime.now(UTC)
                await self._broadcast_to_clients(mountpoint, data)
        except (ConnectionResetError, BrokenPipeError):
            log.info("Source disconnected: %s", session_id)
        finally:
            self._source_sessions.pop(session_id, None)
            self._finish_connection(
                session.get("conn"), bytes_received=session.get("bytes_received", 0)
            )
            await self._cleanup_client_sessions(mountpoint)

    # ---------- NTRIP: клиент (ровер) ----------

    async def handle_client(
        self,
        mountpoint: str,
        headers: dict[str, str],
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        peer: str,
    ) -> None:
        """Обработка подключения клиента (ровера).

        Метод держит соединение до разрыва: без этого NtripServer закроет сокет
        сразу после возврата из dispatch, и сессия клиента не проживёт и секунды.
        """
        from app.ntrip.server import parse_basic_auth

        credentials = parse_basic_auth(headers.get("authorization", ""))
        if not credentials:
            self._register_rejection()
            writer.write(AUTH_REQUIRED.encode())
            await writer.drain()
            writer.close()
            return

        user, password = credentials

        async with session_scope() as session:
            stmt = select(UserModel).where(UserModel.username == user)
            user_model = (await session.execute(stmt)).scalar_one_or_none()

        if (
            not user_model
            or user_model.status != "approved"
            or not verify_password(password, user_model.password_hash)
        ):
            self._register_rejection()
            writer.write(AUTH_REQUIRED.encode())
            await writer.drain()
            writer.close()
            return

        async with session_scope() as session:
            stmt = select(SourceModel).where(
                SourceModel.mountpoint == mountpoint, SourceModel.is_active
            )
            source = (await session.execute(stmt)).scalar_one_or_none()

        if not source:
            # Несуществующий mountpoint — тоже 401 (не раскрываем существование)
            self._register_rejection()
            writer.write(AUTH_REQUIRED.encode())
            await writer.drain()
            writer.close()
            return

        writer.write(NTRIP_OK.encode())
        await writer.drain()

        client_session = {
            "mountpoint": mountpoint,
            "user": user,
            "peer": peer,
            "user_agent": headers.get("user-agent"),
            "connected_at": time.time(),
            "writer": writer,
            "bytes_sent": 0,
            "conn": self._log_connection("client", mountpoint, _peer_ip(peer)),
            # Позиция из GGA заполняется в T-005; position_at — time.time() последнего GGA
            "position": None,
            "position_at": None,
        }

        self._client_sessions.setdefault(mountpoint, []).append(client_session)
        self._total_client_connections += 1
        log.info("Client connected: %s (%s) to %s", peer, user, mountpoint)

        # Восходящий поток ровера (GGA/RTCM) здесь только считаем: разбор позиции — T-005
        try:
            while True:
                if not await reader.read(4096):
                    break
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self._remove_client_session(mountpoint, client_session)
            log.info("Client disconnected: %s (%s) from %s", peer, user, mountpoint)

    def _remove_client_session(self, mountpoint: str, client_session: dict) -> None:
        clients = self._client_sessions.get(mountpoint)
        if clients and client_session in clients:
            clients.remove(client_session)
            if not clients:
                self._client_sessions.pop(mountpoint, None)
        self._finish_connection(
            client_session.get("conn"), bytes_sent=client_session.get("bytes_sent", 0)
        )

    async def _broadcast_to_clients(self, mountpoint: str, data: bytes) -> None:
        """Переслать данные всем клиентам mountpoint."""
        for client in list(self._client_sessions.get(mountpoint, [])):
            writer = client["writer"]
            if writer.is_closing():
                self._remove_client_session(mountpoint, client)
                continue
            try:
                writer.write(data)
                client["bytes_sent"] += len(data)
            except (ConnectionResetError, BrokenPipeError, RuntimeError):
                log.warning("Client disconnect during broadcast: %s", client["peer"])
                self._remove_client_session(mountpoint, client)

    async def _cleanup_client_sessions(self, mountpoint: str) -> None:
        """Закрыть клиентов mountpoint при отключении его источника."""
        for client in self._client_sessions.pop(mountpoint, []):
            self._finish_connection(client.get("conn"), bytes_sent=client.get("bytes_sent", 0))
            try:
                client["writer"].close()
            except Exception:
                pass

    async def _get_active_sources(self) -> list[dict[str, str]]:
        """Список активных источников для sourcetable."""
        sources = []
        async with session_scope() as session:
            stmt = select(SourceModel).where(SourceModel.is_active)
            for src in (await session.execute(stmt)).scalars():
                sources.append(
                    {
                        "mountpoint": src.mountpoint,
                        "identifier": src.mountpoint,
                        "format": "RTCM 3",
                        "nav_system": "GPS+GLO+GAL+BDS",
                        "latitude": str(src.latitude or 0),
                        "longitude": str(src.longitude or 0),
                    }
                )
        return sources

    # ---------- мониторинг (T-003) ----------

    def _source_session_of(self, mountpoint: str) -> dict | None:
        """Сессия источника по mountpoint (активная, если база онлайн)."""
        for session in self._source_sessions.values():
            if session["mountpoint"] == mountpoint:
                return session
        return None

    def _all_client_sessions(self) -> list[dict]:
        return [c for clients in self._client_sessions.values() for c in clients]

    def clients_per_mountpoint(self) -> dict[str, int]:
        """Число подключённых роверов по mountpoint."""
        return {mp: len(clients) for mp, clients in self._client_sessions.items() if clients}

    async def get_status(self) -> dict:
        """Снимок состояния кастера: источники (из БД) с признаком онлайн из сессий."""
        async with session_scope() as session:
            rows = (await session.execute(select(SourceModel))).scalars().all()

        clients_per_mp = self.clients_per_mountpoint()
        sources = []
        for src in rows:
            sess = self._source_session_of(src.mountpoint)
            sources.append(
                {
                    "mountpoint": src.mountpoint,
                    "alive": sess is not None,
                    "peer": sess["peer"] if sess else None,
                    "clients": clients_per_mp.get(src.mountpoint, 0),
                    "last_seen": sess["last_seen"] if sess else None,
                    "bytes_received": sess["bytes_received"] if sess else 0,
                    "latitude": src.latitude,
                    "longitude": src.longitude,
                    "height": src.height,
                    "antenna": src.antenna,
                    "receiver": src.receiver,
                }
            )

        return {
            "sources": sources,
            "clients": clients_per_mp,
            "total_clients": sum(clients_per_mp.values()),
            "rejected_connections": self._rejected,
        }

    def get_clients(self) -> list[dict]:
        """Подключённые роверы (позиционные поля заполнятся в T-005)."""
        now = time.time()
        result = []
        for c in self._all_client_sessions():
            pos = c.get("position") or {}
            result.append(
                {
                    "mountpoint": c["mountpoint"],
                    "ip": c["peer"],
                    "user_agent": c.get("user_agent"),
                    "connected_s": round(now - c["connected_at"], 3),
                    "fix_quality": pos.get("fix_quality"),
                    "num_sats": pos.get("num_sats"),
                    "latitude": pos.get("latitude"),
                    "longitude": pos.get("longitude"),
                    "age_seconds": self._position_age(c, now),
                }
            )
        return result

    def get_positions(self) -> list[dict]:
        """Позиции роверов. Координаты появятся после T-005 (разбор GGA)."""
        now = time.time()
        result = []
        for c in self._all_client_sessions():
            pos = c.get("position") or {}
            position_at = c.get("position_at")
            result.append(
                {
                    "mountpoint": c["mountpoint"],
                    "ip": c["peer"],
                    "latitude": pos.get("latitude"),
                    "longitude": pos.get("longitude"),
                    "fix_quality": pos.get("fix_quality"),
                    "num_sats": pos.get("num_sats"),
                    "hdop": pos.get("hdop"),
                    "altitude": pos.get("altitude"),
                    "geoid_sep": pos.get("geoid_sep"),
                    "age": pos.get("age"),
                    "updated_at": (
                        datetime.fromtimestamp(position_at, UTC) if position_at else None
                    ),
                    "age_seconds": self._position_age(c, now),
                }
            )
        return result

    @staticmethod
    def _position_age(client: dict, now: float) -> float | None:
        """Сколько секунд прошло с последнего GGA от ровера."""
        position_at = client.get("position_at")
        return round(now - position_at, 3) if position_at else None

    def get_connections(self, limit: int = 50) -> list[dict]:
        """Кольцевой журнал подключений, свежие первыми."""
        entries = list(self._connections)
        if limit > 0:
            entries = entries[-limit:]
        return [
            {
                "id": e.id,
                "type": e.type,
                "mountpoint": e.mountpoint,
                "ip_address": e.ip_address,
                "connected_at": e.connected_at,
                "disconnected_at": e.disconnected_at,
                "bytes_sent": e.bytes_sent,
                "bytes_received": e.bytes_received,
            }
            for e in reversed(entries)
        ]

    async def get_statistics(self) -> dict:
        """Накопительная статистика: источники из БД, клиенты — активные сессии."""
        async with session_scope() as session:
            total_sources = len((await session.execute(select(SourceModel.id))).all())

        clients_per_mp = self.clients_per_mountpoint()
        return {
            "total_sources": total_sources,
            "unique_mountpoints": len(clients_per_mp),
            "active_sources": len(self._source_sessions),
            "active_clients": sum(clients_per_mp.values()),
            "total_clients": self._total_client_connections,
        }
