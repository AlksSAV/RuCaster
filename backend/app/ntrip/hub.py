"""Hub — централизованное управление сессиями NTRIP."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from app.core.security import verify_password
from app.db.models import SourceModel
from app.db.session import session_scope
from app.ntrip.server import (
    AUTH_REQUIRED,
    NTRIP_OK,
    SOURCE_OK,
    SOURCE_UNAUTHORIZED,
    build_sourcetable,
)

log = logging.getLogger("rucaster.ntrip")


class NtripHub:
    """Хаб для управления источниками и клиентами."""

    def __init__(self) -> None:
        self._source_sessions: dict[str, dict] = {}
        self._client_sessions: dict[str, list[dict]] = {}

    async def handle_sourcetable(
        self, headers: dict[str, str], writer: asyncio.StreamWriter
    ) -> None:
        """Обработка запроса SOURCETABLE."""
        is_ntrip2 = headers.get("ntrip-version", "").startswith("Ntrip/2.0")

        if is_ntrip2:
            entries = await self._get_active_sources()
            body = build_sourcetable(entries)
            body_bytes = body.encode("utf-8")
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Server: NTRIP RuCaster/1.0\r\n"
                f"Content-Type: gnss/sourcetable\r\n"
                f"Content-Length: {len(body_bytes)}\r\n"
                "Connection: close\r\n\r\n"
            )
            writer.write(response.encode() + body_bytes)
        else:
            body = build_sourcetable(await self._get_active_sources())
            response = "HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n" + body
            writer.write(response.encode())

        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def handle_source(
        self,
        mountpoint: str,
        password: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        peer: str,
    ) -> None:
        """Обработка входящего подключения от источника (базы): SOURCE <pass> /<mp>."""
        # Проверяем пароль
        async with session_scope() as session:
            from sqlalchemy import select

            stmt = select(SourceModel).where(SourceModel.mountpoint == mountpoint)
            result = await session.execute(stmt)
            source = result.scalar_one_or_none()

        if not source or not verify_password(password, source.password):
            writer.write(SOURCE_UNAUTHORIZED.encode())
            await writer.drain()
            writer.close()
            return

        writer.write(SOURCE_OK.encode())
        await writer.drain()

        session_id = f"{mountpoint}:{peer}"
        self._source_sessions[session_id] = {
            "mountpoint": mountpoint,
            "peer": peer,
            "connected_at": datetime.now(UTC),
            "bytes_received": 0,
            "reader": reader,
            "writer": writer,
        }

        log.info("Source connected: %s from %s", mountpoint, peer)

        # Запускаем чтение потока
        await self._read_source_stream(session_id, mountpoint, reader)

    async def _read_source_stream(
        self, session_id: str, mountpoint: str, reader: asyncio.StreamReader
    ) -> None:
        """Чтение данных от источника."""
        session = self._source_sessions.get(session_id)
        if not session:
            return

        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                session["bytes_received"] += len(data)

                # Пересылаем всем клиентам этого mountpoint
                await self._broadcast_to_clients(mountpoint, data)
        except (ConnectionResetError, BrokenPipeError):
            log.info("Source disconnected: %s", session_id)
        finally:
            self._source_sessions.pop(session_id, None)
            await self._cleanup_client_session(mountpoint, session_id)

    async def handle_client(
        self,
        mountpoint: str,
        headers: dict[str, str],
        writer: asyncio.StreamWriter,
        peer: str,
    ) -> None:
        """Обработка подключения клиента (ровера)."""
        # Basic-auth
        auth_header = headers.get("authorization", "")
        from app.ntrip.server import parse_basic_auth

        credentials = parse_basic_auth(auth_header)

        if not credentials:
            writer.write(AUTH_REQUIRED.encode())
            await writer.drain()
            writer.close()
            return

        user, password = credentials

        # Проверяем пользователя
        async with session_scope() as session:
            from sqlalchemy import select

            from app.db.models import UserModel

            stmt = select(UserModel).where(UserModel.username == user)
            result = await session.execute(stmt)
            user_model = result.scalar_one_or_none()

        if (
            not user_model
            or user_model.status != "approved"
            or not verify_password(password, user_model.password_hash)
        ):
            writer.write(AUTH_REQUIRED.encode())
            await writer.drain()
            writer.close()
            return

        # Проверяем, есть ли такой mountpoint
        async with session_scope() as session:
            from sqlalchemy import select

            from app.db.models import SourceModel

            stmt = select(SourceModel).where(
                SourceModel.mountpoint == mountpoint, SourceModel.is_active
            )
            result = await session.execute(stmt)
            source = result.scalar_one_or_none()

        if not source:
            # НЕСУЩЕСТВУЮЩИЙ mountpoint — тоже 401 (не раскрываем существование)
            writer.write(AUTH_REQUIRED.encode())
            await writer.drain()
            writer.close()
            return

        writer.write(NTRIP_OK.encode())
        await writer.drain()

        # Регистрируем сессию клиента
        client_session = {
            "mountpoint": mountpoint,
            "user": user,
            "peer": peer,
            "connected_at": time.time(),
            "writer": writer,
            "bytes_sent": 0,
        }

        if mountpoint not in self._client_sessions:
            self._client_sessions[mountpoint] = []
        self._client_sessions[mountpoint].append(client_session)

        log.info("Client connected: %s (%s) to %s", peer, user, mountpoint)

    async def _broadcast_to_clients(self, mountpoint: str, data: bytes) -> None:
        """Переслать данные всем клиентам mountpoint."""
        clients = self._client_sessions.get(mountpoint, [])
        for client in clients:
            try:
                client["writer"].write(data)
                client["bytes_sent"] += len(data)
            except (ConnectionResetError, BrokenPipeError):
                log.warning("Client disconnect during broadcast: %s", client["peer"])
                client["writer"].close()

    async def _get_active_sources(self) -> list[dict[str, str]]:
        """Получить список активных источников для sourcetable."""
        sources = []
        async with session_scope() as session:
            from sqlalchemy import select

            from app.db.models import SourceModel

            stmt = select(SourceModel).where(SourceModel.is_active)
            result = await session.execute(stmt)
            for src in result.scalars():
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

    async def _cleanup_client_session(self, mountpoint: str, source_id: str) -> None:
        """Закрыть клиентов mountpoint при отключении его источника."""
        clients = self._client_sessions.pop(mountpoint, [])
        for c in clients:
            try:
                c["writer"].close()
            except Exception:
                pass
