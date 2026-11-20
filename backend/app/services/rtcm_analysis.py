"""RTCM-анализ потока (T-009): скользящее окно, счётчики, вердикт rtk_ready.

На каждый mountpoint-источник ведётся скользящее окно (по умолчанию 60 с):
кадры, CRC-ошибки, мусорные байты, статистика по типам сообщений. По содержимому
окна выносится вердикт rtk_ready (наличие координат станции, MSM-наблюдений,
эфемерид, приемлемый уровень ошибок).

Полное декодирование сообщений (спутники, CNR) — вне объёма T-009.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from app.gnss.parsers import RtcFrame, crc24q

# Окно анализа, секунд
DEFAULT_WINDOW_S = 60.0

# Типы сообщений по категориям (RTCM 3.x)
STATION_COORD_TYPES = {1005, 1006}
_GPS_MSM = {1071, 1072, 1073, 1074, 1075, 1076, 1077}
_GLONASS_MSM = {1081, 1082, 1083, 1084, 1085, 1086, 1087}
_GALILEO_MSM = {1091, 1092, 1093, 1094, 1095, 1096, 1097}
_BEIDOU_MSM = {1101, 1102, 1103, 1104, 1105, 1106, 1107}
MSM_TYPES = _GPS_MSM | _GLONASS_MSM | _GALILEO_MSM | _BEIDOU_MSM
# Legacy-наблюдения (L1/L2/L1&L2) тоже считаются наблюдениями
LEGACY_OBS_TYPES = {1001, 1002, 1003, 1004, 1012, 1013, 1014}
OBS_TYPES = MSM_TYPES | LEGACY_OBS_TYPES
EPHEMERIS_TYPES = {
    1019,  # GPS ephemerides
    1020,  # GLONASS ephemerides
    1042,  # BeiDou
    1043,  # BeiDou GEO
    1044,  # BeiDou
    1045,  # Galileo I/NAV
    1046,  # Galileo F/NAV
    63,  # BeiDou (CNES)
    1021,  # QZSS
    1022,
    1023,
    1024,
}

# Человекочитаемые имена для частых типов (остальные — по ID)
MSG_NAMES = {
    1001: "GPS L1-Only RTK Observables",
    1002: "GPS L1&L2 RTK Observables",
    1003: "GPS L1&L2 Antispoofing RTK Observables",
    1004: "GPS Extended L1&L2 RTK Observables",
    1005: "Stationary RTK Reference Station ARP",
    1006: "Stationary RTK Reference ARP with Antenna Height",
    1008: "Antenna Descriptor",
    1009: "GLONASS L1 RTK Observables",
    1010: "GLONASS L1&L2 RTK Observables",
    1011: "GLONASS L1&L2 Antispoofing RTK Observables",
    1012: "GLONASS Extended L1&L2 RTK Observables",
    1019: "GPS Ephemerides",
    1020: "GLONASS Ephemerides",
    1029: "Unicode Text String",
    1033: "Receiver and Antenna Descriptors",
    1042: "BeiDou Ephemerides",
    1044: "BeiDou Ephemerides",
    1045: "Galileo I/NAV Ephemerides",
    1046: "Galileo F/NAV Ephemerides",
    1074: "GPS MSM4",
    1075: "GPS MSM5",
    1076: "GPS MSM6",
    1077: "GPS MSM7",
    1084: "GLONASS MSM4",
    1085: "GLONASS MSM5",
    1086: "GLONASS MSM6",
    1087: "GLONASS MSM7",
    1094: "Galileo MSM4",
    1095: "Galileo MSM5",
    1096: "Galileo MSM6",
    1097: "Galileo MSM7",
    1104: "BeiDou MSM4",
    1105: "BeiDou MSM5",
    1106: "BeiDou MSM6",
    1107: "BeiDou MSM7",
}


def frame_name(msg_type: int) -> str:
    return MSG_NAMES.get(msg_type, f"RTCM {msg_type}")


def extract_rtcm3_frames(buf: bytearray) -> tuple[list[RtcFrame], int]:
    """Выделить полные RTCM3-кадры из буфера; остаток оставить в буфере.

    Возвращает (кадры, junk_bytes) — junk_bytes это число байтов, отброшенных
    при поиске start-байта 0xD3 и при очистке переполнения.
    """
    frames: list[RtcFrame] = []
    junk = 0
    while True:
        idx = buf.find(b"\xd3")
        if idx < 0:
            junk += len(buf)
            buf.clear()
            break
        if idx > 0:
            junk += idx
            del buf[:idx]
        # нужен заголовок 3 байта
        if len(buf) < 3:
            break
        length = (buf[1] << 8) | buf[2]
        if length < 7 or length > 0x3FF:
            # ложный start-байт
            del buf[:1]
            junk += 1
            continue
        need = 3 + length + 3
        if len(buf) < need:
            break  # кадр ещё не докачан
        body = bytes(buf[3 : 3 + length])
        stored = (buf[3 + length] << 16) | (buf[4 + length] << 8) | buf[5 + length]
        crc_ok = crc24q(bytes(buf[: 3 + length])) == stored
        msg_type = (body[0] << 4) | (body[1] >> 4)
        frames.append(RtcFrame(msg_type=msg_type, length=length, crc_ok=crc_ok, data=body))
        del buf[:need]
        if len(buf) > 65536:  # защита от роста без кадров
            junk += len(buf)
            buf.clear()
    return frames, junk


@dataclass
class _FrameRecord:
    ts: float
    msg_type: int
    crc_ok: bool
    size: int


@dataclass
class RtcmAnalyzer:
    """Скользящее окно RTCM-потока одного mountpoint."""

    window_s: float = DEFAULT_WINDOW_S
    _records: deque[_FrameRecord] = field(default_factory=deque)
    _buf: bytearray = field(default_factory=bytearray)
    _junk_total: int = 0
    _bytes_total: int = 0
    started_at: float | None = None
    last_feed: float | None = None

    def feed(self, data: bytes, now: float | None = None) -> None:
        """Обработать чанк потока: выделить кадры, обновить окно."""
        if now is None:
            now = time.monotonic()
        if self.started_at is None:
            self.started_at = now
        self.last_feed = now
        self._bytes_total += len(data)
        self._buf.extend(data)
        frames, junk = extract_rtcm3_frames(self._buf)
        self._junk_total += junk
        for fr in frames:
            self._records.append(
                _FrameRecord(
                    ts=now,
                    msg_type=fr.msg_type,
                    crc_ok=fr.crc_ok,
                    size=1 + 2 + fr.length + 3,  # заголовок + payload + CRC
                )
            )
        self._purge(now)

    def _purge(self, now: float) -> None:
        cutoff = now - self.window_s
        while self._records and self._records[0].ts < cutoff:
            self._records.popleft()

    # ---------- отчёт ----------

    def report(self, connected: bool, now: float | None = None) -> dict:
        """Снимок окна в формате API анализа."""
        if now is None:
            now = time.monotonic()
        self._purge(now)
        recs = list(self._records)
        duration = (
            min(self.window_s, now - self.started_at) if self.started_at is not None else 0.0
        )
        duration = max(duration, 0.0)

        frames_ok = sum(1 for r in recs if r.crc_ok)
        crc_errors = sum(1 for r in recs if not r.crc_ok)
        window_bytes = sum(r.size for r in recs)

        by_type: dict[int, list] = {}
        for r in recs:
            e = by_type.setdefault(r.msg_type, [0, 0, r.ts])
            e[0] += 1
            e[1] += r.size
            e[2] = max(e[2], r.ts)

        messages = [
            {
                "id": mt,
                "name": frame_name(mt),
                "count": cnt,
                "rate_hz": round(cnt / duration, 3) if duration > 0 else 0.0,
                "avg_size": round(total / cnt, 1),
                "last_seen": round(now - last_ts, 3),
            }
            for mt, (cnt, total, last_ts) in sorted(by_type.items())
        ]

        seen = set(by_type)
        checks = [
            {
                "name": "station_coordinates",
                "ok": bool(seen & STATION_COORD_TYPES),
                "note": "нужны 1005/1006 в окне",
            },
            {
                "name": "observations",
                "ok": bool(seen & OBS_TYPES),
                "note": "нужны MSM4+ (1074..1107) или legacy 1001..1012",
            },
            {
                "name": "ephemerides",
                "ok": bool(seen & EPHEMERIS_TYPES),
                "note": "нужны 1019/1020/1042-1046/63",
            },
            {
                "name": "crc",
                "ok": frames_ok > 0 and crc_errors == 0,
                "note": "нет кадров с неверным CRC",
            },
            {
                "name": "streaming",
                "ok": connected and frames_ok > 0,
                "note": "источник онлайн и шлются кадры",
            },
        ]
        rtk_ready = all(c["ok"] for c in checks)

        return {
            "window_s": self.window_s,
            "connected": connected,
            "updated_at": self.last_feed,
            "report": {
                "session": {
                    "duration_s": round(duration, 3),
                    "bytes_total": self._bytes_total,
                    "window_bytes": window_bytes,
                    "frames_ok": frames_ok,
                    "crc_errors": crc_errors,
                    "junk_bytes": self._junk_total,
                },
                "messages": messages,
                "constellations": self._constellations(seen),
                "verdict": {"rtk_ready": rtk_ready, "checks": checks},
            },
        }

    @staticmethod
    def _constellations(seen: set[int]) -> dict[str, bool]:
        return {
            "GPS": bool(seen & (_GPS_MSM | {1001, 1002, 1003, 1004, 1019})),
            "GLONASS": bool(seen & (_GLONASS_MSM | {1009, 1010, 1011, 1012, 1020})),
            "Galileo": bool(seen & (_GALILEO_MSM | {1045, 1046})),
            "BeiDou": bool(seen & (_BEIDOU_MSM | {1042, 1043, 1044, 63})),
        }
