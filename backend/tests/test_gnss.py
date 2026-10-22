"""Тесты GNSS-парсеров: NMEA GGA, RTCM3, гео-конвертации."""

from __future__ import annotations

from app.gnss.parsers import NmeaGGA, parse_gga, parse_rtcm3, utm_to_wgs84, wgs84_to_utm

# Валидная строка GGA из замера (fix=4, 12 спутников, HDOP 0.8)
GGA_FIX4 = "$GNGGA,182839.12,3916.48212,N,08952.49420,W,4,12,0.8,150.0,M,14.0,M,1.0,0000*4A"


class TestParseGga:
    def test_valid_gga(self):
        gga = parse_gga(GGA_FIX4)
        assert gga is not None
        assert gga.fix_quality == 4
        assert gga.num_sats == 12
        assert gga.hdop == 0.8
        assert gga.altitude == 150.0
        assert gga.geoid_sep == 14.0
        assert gga.age == 1.0

    def test_coordinates(self):
        gga = parse_gga(GGA_FIX4)
        assert gga is not None
        # 3916.48212' N -> ~39.2747
        assert abs(gga.latitude - 39.274702) < 1e-4
        # 08952.49420' W -> ~-89.8749
        assert abs(gga.longitude + 89.874903) < 1e-4

    def test_no_fix_returns_none(self):
        gga_no_fix = "$GNGGA,120000.00,5500.00000,N,03700.00000,E,0,00,99.9,0.0,M,0.0,M,,"
        assert parse_gga(gga_no_fix) is None

    def test_invalid_inputs(self):
        assert parse_gga("") is None
        assert parse_gga("not a sentence") is None
        assert parse_gga("$GPXXX,1,2,3") is None

    def test_returns_dataclass(self):
        gga = parse_gga(GGA_FIX4)
        assert isinstance(gga, NmeaGGA)


class TestParseRtcm3:
    @staticmethod
    def _make_frame(msg_type: int, payload: bytes) -> bytes:
        """Собрать синтетический RTCM3-кадр (CRC не валидируется парсером)."""
        # Заголовок: 0xD3 + 2 байта длины (big-endian)
        payload_len = 3 + len(payload)  # 3 байта заголовка msg + payload
        length_bytes = bytes([(payload_len >> 8) & 0xFF, payload_len & 0xFF])
        # Первые 12 бит msg_type в первых 12 битах payload (после заголовка)
        p0 = (msg_type >> 4) & 0xFF
        p1 = ((msg_type & 0x0F) << 4) & 0xFF
        body = bytes([p0, p1]) + payload
        return bytes([0xD3]) + length_bytes + body + b"\x00\x00"

    def test_single_frame(self):
        frame = self._make_frame(1005, bytes(9))
        frames = parse_rtcm3(frame)
        assert len(frames) == 1
        assert frames[0].msg_type == 1005

    def test_junk_skipped(self):
        frame = self._make_frame(1077, bytes(20))
        data = b"\x00\x01\x02junk" + frame
        frames = parse_rtcm3(data)
        assert len(frames) == 1
        assert frames[0].msg_type == 1077

    def test_empty(self):
        assert parse_rtcm3(b"") == []
        assert parse_rtcm3(b"\x00" * 10) == []

    def test_truncated_frame(self):
        frame = self._make_frame(1004, bytes(30))
        frames = parse_rtcm3(frame[:-5])
        assert frames == []


class TestGeo:
    def test_wgs84_to_utm_moscow(self):
        # Москва: 55.7558, 37.6173 -> зона 37N
        r = wgs84_to_utm(55.7558, 37.6173)
        assert r["zone"] == "37"
        assert r["north"] is True
        assert 200_000 < r["easting"] < 800_000
        assert 6_000_000 < r["northing"] < 6_300_000

    def test_wgs84_to_utm_southern_hemisphere(self):
        # Сантьяго: -33.4489, -70.6693 -> зона 19S
        r = wgs84_to_utm(-33.4489, -70.6693)
        assert r["zone"] == "19"
        assert r["north"] is False

    def test_utm_roundtrip(self):
        lat, lon = 48.8566, 2.3522  # Париж
        utm = wgs84_to_utm(lat, lon)
        lat2, lon2 = utm_to_wgs84(utm["easting"], utm["northing"], int(utm["zone"]), utm["north"])
        # обратное преобразование точное в пределах зоны
        assert abs(lat2 - lat) < 1e-4
        assert abs(lon2 - lon) < 1e-4
