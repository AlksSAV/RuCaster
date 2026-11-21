"""Proxy service: управление подменами координат (T-008).

Режимы:
- relay  — подключение к внешнему NTRIP-кастеру и ретрансляция потока
- absolute — подмена RTCM 1005/1006 на фиктивные координаты (ECEF)
- offset — смещение ARP в RTCM 1005/1006 на de/dn/du

Каждая подмена публикует модифицированный поток на
`<source_mountpoint>_SHIFTED` (или `<source_mountpoint>_RELAY` для relay-режима).
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.gnss.parsers import crc24q, parse_rtcm3

if TYPE_CHECKING:
    from app.ntrip.hub import NtripHub

log = logging.getLogger("rucaster.proxy")


def _frame_from_payload(payload: bytes) -> bytes:
    """Обернуть payload в RTCM3-кадр (0xD3 + len + body + CRC24Q)."""
    length = len(payload)
    header = bytes([0xD3, (length >> 8) & 0xFF, length & 0xFF])
    crc = crc24q(header + payload)
    return header + payload + bytes([crc >> 16, (crc >> 8) & 0xFF, crc & 0xFF])


def _split_rtcm_stream(buf: bytes) -> tuple[bytes, bytes]:
    """Разделить поток на (полные кадры, остаток-недомерок).

    Сканирование как в parse_rtcm3: за кадром 0xD3+length следует payload+CRC.
    Байты до первого валидного заголовка относятся к «полным» (прокидываются
    как есть). Остаток — хвост с неполным кадром (ждём продолжения).
    """
    i = 0
    n = len(buf)
    while i < n:
        if buf[i] != 0xD3:
            i += 1
            continue
        if i + 3 > n:
            return buf[:i], buf[i:]
        length = (buf[i + 1] << 8) | buf[i + 2]
        if length < 7 or length > 0x3FF:
            i += 1
            continue
        end = i + 3 + length + 3
        if end > n:
            return buf[:i], buf[i:]
        i = end
    return buf, b""


@dataclass
class RelaySession:
    """Состояние relay-сессии: upstream-соединение."""

    target_mountpoint: str
    src_host: str
    src_port: int
    src_mountpoint: str
    src_user: str
    src_password: str
    task: asyncio.Task | None = None


class ProxyService:
    """Управление подменами координат и relay-сессиями."""

    def __init__(self) -> None:
        self._proxies: dict[str, dict] = {}
        self._relay_sessions: dict[str, RelaySession] = {}
        # Буферы неполных RTCM-кадров по proxy_id
        self._buffers: dict[str, bytearray] = {}
        # hub — ссылка на NtripHub для broadcast relay-клиентам
        self.hub: NtripHub | None = None

    # ---------- CRUD ----------

    def add_proxy(
        self,
        proxy_id: str,
        owner_id: str,
        source_mountpoint: str,
        target_mountpoint: str,
        mode: str,
        serve_mountpoint: str | None = None,
        dest_port: int | None = None,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        de: float | None = None,
        dn: float | None = None,
        du: float | None = None,
        relay_host: str | None = None,
        relay_port: int | None = None,
        relay_mountpoint: str | None = None,
        relay_user: str | None = None,
        relay_password: str | None = None,
    ) -> None:
        self._proxies[proxy_id] = {
            "id": proxy_id,
            "owner_id": owner_id,
            "source_mountpoint": source_mountpoint,
            "target_mountpoint": target_mountpoint,
            "mode": mode,
            "serve_mountpoint": serve_mountpoint,
            "dest_port": dest_port,
            "x": x,
            "y": y,
            "z": z,
            "de": de,
            "dn": dn,
            "du": du,
            "relay_host": relay_host,
            "relay_port": relay_port,
            "relay_mountpoint": relay_mountpoint,
            "relay_user": relay_user,
            "relay_password": relay_password,
            "is_active": True,
            "created_at": datetime.now(UTC),
        }

    def delete_proxy(self, proxy_id: str) -> dict | None:
        return self._proxies.pop(proxy_id, None)

    def get_proxy(self, proxy_id: str) -> dict | None:
        return self._proxies.get(proxy_id)

    def get_proxies_by_owner(self, owner_id: str) -> list[dict]:
        return [p for p in self._proxies.values() if p["owner_id"] == owner_id]

    def get_active_by_source(self, source_mountpoint: str) -> list[dict]:
        return [
            p
            for p in self._proxies.values()
            if p["is_active"] and p["source_mountpoint"] == source_mountpoint
        ]

    def deactivate_all(self) -> None:
        for p in self._proxies.values():
            p["is_active"] = False

    def get_all_active(self) -> list[dict]:
        return [p for p in self._proxies.values() if p["is_active"]]

    # ---------- Relay ----------

    async def activate_relay(
        self,
        source_mountpoint: str,
        target_mountpoint: str,
        src_host: str,
        src_port: int,
        src_mountpoint: str,
        src_user: str,
        src_password: str,
    ) -> None:
        if target_mountpoint in self._relay_sessions:
            await self.stop_relay(target_mountpoint)

        session = RelaySession(
            target_mountpoint=target_mountpoint,
            src_host=src_host,
            src_port=src_port,
            src_mountpoint=src_mountpoint,
            src_user=src_user,
            src_password=src_password,
        )
        session.task = asyncio.create_task(
            self._relay_task(session), name=f"relay-{target_mountpoint}"
        )
        self._relay_sessions[target_mountpoint] = session

    async def stop_relay(self, target_mountpoint: str) -> None:
        session = self._relay_sessions.pop(target_mountpoint, None)
        if session and session.task and not session.task.done():
            session.task.cancel()
            try:
                await session.task
            except asyncio.CancelledError:
                pass

    async def check_upstream(self, proxy: dict) -> dict:
        if proxy["mode"] != "relay":
            return {"ok": False, "error": "not relay mode"}

        src_host = proxy.get("relay_host")
        src_port = proxy.get("relay_port") or 2101
        src_mountpoint = proxy.get("relay_mountpoint") or ""

        if not src_host or not src_mountpoint:
            return {"ok": False, "error": "host/mountpoint not set"}

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(src_host, src_port),
                timeout=10.0,
            )
        except (TimeoutError, OSError) as exc:
            return {"ok": False, "error": str(exc)}

        try:
            auth = base64.b64encode(
                f"{proxy.get('relay_user', '')}:{proxy.get('relay_password', '')}".encode()
            ).decode()
            request = (
                f"GET /{src_mountpoint} HTTP/1.1\r\n"
                f"Host: {src_host}\r\n"
                f"Icecast: 2.0\r\n"
                f"Authorization: Basic {auth}\r\n"
                f"Accept: */*\r\n"
                f"User-Agent: RuCaster-check\r\n"
                f"Connection: close\r\n\r\n"
            ).encode()
            writer.write(request)
            await writer.drain()

            buf = bytearray()
            deadline = asyncio.get_event_loop().time() + 10.0
            while b"\r\n\r\n" not in buf:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    return {"ok": False, "error": "timeout"}
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=remaining)
                    if not chunk:
                        return {"ok": False, "error": "upstream closed"}
                    buf.extend(chunk)
                except TimeoutError:
                    return {"ok": False, "error": "timeout reading headers"}

            header = buf[: buf.find(b"\r\n\r\n")].decode(errors="replace").lower()
            if "200" in header:
                return {"ok": True, "error": None}
            return {"ok": False, "error": f"HTTP {header[:50]}"}
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _relay_task(self, session: RelaySession) -> None:
        """Relay: connect upstream -> read -> broadcast to target_mountpoint."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(session.src_host, session.src_port),
                timeout=15.0,
            )
        except (TimeoutError, OSError) as exc:
            log.error(
                "Relay upstream connect failed %s:%d/%s: %s",
                session.src_host,
                session.src_port,
                session.target_mountpoint,
                exc,
            )
            return

        try:
            auth = base64.b64encode(f"{session.src_user}:{session.src_password}".encode()).decode()
            request = (
                f"GET /{session.src_mountpoint} HTTP/1.1\r\n"
                f"Host: {session.src_host}:{session.src_port}\r\n"
                f"Icecast: 2.0\r\n"
                f"Authorization: Basic {auth}\r\n"
                f"Accept: */*\r\n"
                f"User-Agent: RuCaster-proxy\r\n"
                f"\r\n"
            ).encode()
            writer.write(request)
            await writer.drain()

            buf = bytearray()
            while b"\r\n\r\n" not in buf:
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=10.0)
                    if not chunk:
                        log.error("Relay upstream closed during headers")
                        return
                    buf.extend(chunk)
                except TimeoutError:
                    log.error("Relay upstream timeout during headers")
                    return

            header = buf[: buf.find(b"\r\n\r\n")].decode(errors="replace").lower()
            if "200" not in header:
                log.error("Relay upstream non-200: %s", header[:200])
                return

            data = buf[buf.find(b"\r\n\r\n") + 4 :]

            while True:
                if data:
                    if self.hub:
                        await self.hub._broadcast_to_clients(session.target_mountpoint, data)
                    data = b""

                try:
                    chunk = await asyncio.wait_for(reader.read(65536), timeout=30.0)
                    if not chunk:
                        return
                    data = chunk
                except TimeoutError:
                    if not self.hub or not self.hub._client_sessions.get(
                        session.target_mountpoint
                    ):
                        return

        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            try:
                reader.feed_eof()
            except Exception:
                pass

    # ---------- RTCM-трансформация ----------

    def transform_chunk(self, proxy: dict, data: bytes) -> bytes:
        """Трансформировать чанк потока с переносом неполного кадра в буфер.

        RTCM-кадры могут разрезаться границей чанка, поэтому хвост с неполным
        кадром сохраняется до следующего чанка (иначе клиент получит обрывок).
        """
        if proxy["mode"] == "relay":
            return data

        buf = self._buffers.setdefault(proxy["id"], bytearray())
        buf.extend(data)
        complete, rest = _split_rtcm_stream(bytes(buf))
        buf.clear()
        buf.extend(rest)
        if not complete:
            return b""
        return self.transform_rtcm(complete, proxy)

    @staticmethod
    def transform_rtcm(data: bytes, proxy: dict) -> bytes:
        """Модифицировать RTCM3-кадры (absolute/offset)."""
        mode = proxy["mode"]
        if mode == "relay":
            return data

        frames = parse_rtcm3(data)
        if not frames:
            return data

        modified = False
        new_frames: list[bytes] = []

        for frame in frames:
            mt = frame.msg_type
            payload = frame.data

            if mt in (1005, 1006) and mode in ("absolute", "offset"):
                new_payload = _modify_arp(payload, proxy, mt)
                if new_payload is not None:
                    payload = new_payload
                    modified = True

            # Кадры пересобираются с корректным CRC; для неизменённого payload
            # результат побайтово совпадает с оригиналом (CRC детерминирован).
            new_frames.append(_frame_from_payload(payload))

        return b"".join(new_frames) if modified else data


def _modify_arp(payload: bytes, proxy: dict, msg_type: int) -> bytes | None:
    """Пересобрать payload RTCM 1005/1006 с новыми ARP-координатами.

    Меняются только битовые поля DF025/DF026/DF027 (ECEF X/Y/Z), остальные
    поля (номер станции, индикаторы созвездий, высота антенны 1006) берутся
    из оригинала без изменений.

    Раскладка 1005: DF002(12) DF003(12) DF021(6) DF022(1) DF023(1) DF024(1)
    DF141(1) DF025(38) DF142(1) DF001_1(1) DF026(38) DF364(2) DF027(38)
    [+ DF028(16) для 1006].
    """
    try:
        import pyrtcm

        msg = pyrtcm.RTCMMessage(payload)
        x = float(msg.DF025)
        y = float(msg.DF026)
        z = float(msg.DF027)
    except Exception:
        log.debug("Cannot parse RTCM %d payload for proxy", msg_type)
        return None

    if proxy["mode"] == "absolute":
        if proxy["x"] is not None and proxy["y"] is not None and proxy["z"] is not None:
            x, y, z = proxy["x"], proxy["y"], proxy["z"]
    elif proxy["mode"] == "offset":
        x += proxy.get("de") or 0.0
        y += proxy.get("dn") or 0.0
        z += proxy.get("du") or 0.0

    bits = "".join(f"{byte:08b}" for byte in payload)

    def _splice(bits: str, start: int, width: int, value: float) -> str:
        raw = int(round(value * 10000))
        raw &= (1 << width) - 1
        return bits[:start] + format(raw, f"0{width}b") + bits[start + width :]

    bits = _splice(bits, 34, 38, x)
    bits = _splice(bits, 74, 38, y)
    bits = _splice(bits, 114, 38, z)

    padded = bits + "0" * (-len(bits) % 8)
    return int(padded, 2).to_bytes(len(padded) // 8, "big")
