"""NTRIP TCP-сервер (порт 2101).

Поддерживает:
- SOURCETABLE (GET /) для NTRIP 1.0 и 2.0
- SOURCE <pass> /<mp> — входящий поток от базы
- GET /<mp> + Basic-auth — исходящий стрим для ровера
"""

from __future__ import annotations

import asyncio
import base64
import logging

from app.core.config import settings

log = logging.getLogger("rucaster.ntrip")

NTRIP_OK = "ICY 200 OK\r\n"
AUTH_REQUIRED = (
    "HTTP/1.0 401 Unauthorized\r\n"
    'WWW-Authenticate: Basic realm="NTRIP"\r\n'
    "Content-Type: text/plain\r\n\r\n"
)
SOURCE_OK = "ICY 200 OK\r\n"
SOURCE_UNAUTHORIZED = "ICY 401 Mountpoint or password incorrect\r\n"


def parse_basic_auth(header: str) -> tuple[str, str] | None:
    """Разобрать заголовок Authorization: Basic ..."""
    if not header.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header.split(None, 1)[1]).decode("utf-8")
    except Exception:
        return None
    if ":" not in decoded:
        return None
    user, _, password = decoded.partition(":")
    return user, password


def build_sourcetable(entries: list[dict[str, str]]) -> str:
    """Собрать тело sourcetable по активным источникам."""
    lines = ["SOURCETABLE 200 OK", "Server: RuCaster", "Content-Type: text/plain", ""]
    for e in entries:
        # STR;mp;ident;format;carrier;nav;sources;encryption;auth;winter;lat;lon;
        #     latAcc;lonAcc;height;geoidsep;date;expiry;msm;network;station;bitrate
        lines.append(
            "STR;{mp};{ident};{fmt};0;{nav};N/A;N;N;N;{lat};{lon};0;0;0;0;;;N;N;N;".format(
                mp=e.get("mountpoint", ""),
                ident=e.get("identifier", e.get("mountpoint", "")),
                fmt=e.get("format", "RTCM 3"),
                nav=e.get("nav_system", "GPS+GLO+GAL+BDS"),
                lat=e.get("latitude", "0"),
                lon=e.get("longitude", "0"),
            )
        )
    lines.append("ENDSOURCETABLE")
    return "\r\n".join(lines) + "\r\n"


class NtripServer:
    """Асинхронный NTRIP-сервер поверх asyncio."""

    def __init__(self, hub) -> None:
        self._hub = hub
        self._server: asyncio.Server | None = None
        self._running = False
        self.active_connections = 0
        self.rejected_connections = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, settings.ntrip_host, settings.ntrip_port
        )
        self._running = True
        log.info("NTRIP listening on %s:%s", settings.ntrip_host, settings.ntrip_port)

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            log.info("NTRIP stopped")

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        peer_str = f"{peer[0]}:{peer[1]}" if peer else "unknown"
        self.active_connections += 1
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=30.0)
            if not request_line:
                return
            headers = await self._read_headers(reader)
            await self._dispatch(
                request_line.decode(errors="replace").strip(), headers, reader, writer, peer_str
            )
        except TimeoutError:
            log.debug("timeout from %s", peer_str)
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception:
            log.exception("ntrip handler error from %s", peer_str)
        finally:
            self.active_connections -= 1
            try:
                writer.close()
            except Exception:
                pass

    @staticmethod
    async def _read_headers(reader: asyncio.StreamReader) -> dict[str, str]:
        headers: dict[str, str] = {}
        while True:
            line = await reader.readline()
            if not line or line in (b"\r\n", b"\n"):
                break
            decoded = line.decode(errors="replace").strip()
            if ":" in decoded:
                key, _, value = decoded.partition(":")
                headers[key.strip().lower()] = value.strip()
        return headers

    async def _dispatch(
        self,
        request_line: str,
        headers: dict[str, str],
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        peer: str,
    ) -> None:
        parts = request_line.split()
        if len(parts) < 2:
            writer.write(AUTH_REQUIRED.encode())
            await writer.drain()
            return

        method, target = parts[0].upper(), parts[1]

        # Входящий поток от базы: SOURCE <pass> /<mp>
        if method == "SOURCE":
            password = parts[1] if len(parts) > 1 else ""
            mp = parts[2].lstrip("/") if len(parts) > 2 else ""
            await self._hub.handle_source(mp, password, reader, writer, peer)
            return

        if method == "GET":
            # Sourcetable
            if target in ("/", "/streams"):
                await self._hub.handle_sourcetable(headers, writer)
                return
            # Стрим роверу
            await self._hub.handle_client(target.lstrip("/"), headers, reader, writer, peer)
            return

        writer.write(AUTH_REQUIRED.encode())
        await writer.drain()

    @property
    def running(self) -> bool:
        return self._server is not None and self._running
