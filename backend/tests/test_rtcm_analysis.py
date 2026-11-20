"""Тесты RTCM-анализа потока (T-009): extract_rtcm3_frames и RtcmAnalyzer.

Используются синтетические RTCM3-кадры с валидным CRC-24Q — без железа.
"""

from __future__ import annotations

from app.gnss.parsers import crc24q
from app.services.rtcm_analysis import RtcmAnalyzer, extract_rtcm3_frames


def make_frame(msg_type: int, body: bytes = b"\x00" * 8) -> bytes:
    """Собрать RTCM3-кадр с валидным CRC. body — байты после 12-битного ID."""
    p0 = (msg_type >> 4) & 0xFF
    p1 = (((msg_type & 0x0F) << 4) | (body[0] >> 4)) & 0xFF
    payload = bytes([p0, p1]) + body[1:]
    length = len(payload)
    header = bytes([0xD3, (length >> 8) & 0xFF, length & 0xFF])
    crc = crc24q(header + payload)
    return header + payload + bytes([crc >> 16, (crc >> 8) & 0xFF, crc & 0xFF])


def bad_crc_frame(msg_type: int) -> bytes:
    f = bytearray(make_frame(msg_type))
    f[-1] ^= 0xFF  # испортить CRC
    return bytes(f)


class TestExtractFrames:
    def test_single(self):
        buf = bytearray(make_frame(1005))
        frames, junk = extract_rtcm3_frames(buf)
        assert len(frames) == 1
        assert frames[0].msg_type == 1005
        assert frames[0].crc_ok
        assert junk == 0
        assert buf == b""

    def test_frame_split_across_chunks(self):
        full = make_frame(1077)
        buf = bytearray()
        buf.extend(full[:4])
        frames, _ = extract_rtcm3_frames(buf)
        assert frames == []
        buf.extend(full[4:])
        frames, _ = extract_rtcm3_frames(buf)
        assert len(frames) == 1
        assert frames[0].msg_type == 1077

    def test_junk_between_frames_skipped(self):
        data = b"\x01\x02\x03" + make_frame(1005) + b"\xff" + make_frame(1087)
        frames, junk = extract_rtcm3_frames(bytearray(data))
        assert [f.msg_type for f in frames] == [1005, 1087]
        assert junk == 4  # 3 байта мусора + 1 перед вторым кадром

    def test_bad_crc_flagged(self):
        data = make_frame(1005) + bad_crc_frame(1005)
        frames, _ = extract_rtcm3_frames(bytearray(data))
        assert len(frames) == 2
        assert frames[0].crc_ok
        assert not frames[1].crc_ok

    def test_false_start_byte(self):
        """0xD3 внутри payload не должен ломать разбор: ложный start отбрасывается."""
        # кадр, где тело начинается с 0xD3 (msg_type 1073: p0 = 0x43? нет, подберём)
        # msg_type=1073 -> p0 = 1073>>4 = 67 = 0x43; возьмём msg 1008 -> p0=0x3F.
        # Проще: вставим 0xD3 как мусорный байт перед валидным кадром
        data = b"\xd3\x00\x05" + make_frame(1005)  # псевдо-заголовок с length=5 (<7)
        frames, junk = extract_rtcm3_frames(bytearray(data))
        # length=5 отбраковывается, junk += 1 (ложный 0xD3), затем кадр читается
        assert len(frames) == 1
        assert frames[0].msg_type == 1005
        assert junk >= 1

    def test_empty_buffer(self):
        buf = bytearray()
        frames, junk = extract_rtcm3_frames(buf)
        assert frames == []
        assert junk == 0


class TestAnalyzerWindow:
    def test_counts_frames(self):
        a = RtcmAnalyzer(window_s=60.0)
        stream = make_frame(1005) + make_frame(1077) + make_frame(1087)
        a.feed(stream, now=100.0)
        r = a.report(connected=True, now=120.0)["report"]
        assert r["session"]["frames_ok"] == 3
        assert r["session"]["crc_errors"] == 0

    def test_window_eviction(self):
        a = RtcmAnalyzer(window_s=60.0)
        a.feed(make_frame(1005), now=0.0)
        a.feed(make_frame(1077), now=50.0)
        # на момент t=100 кадр t=0 выпал из окна, t=50 остался
        r = a.report(connected=True, now=100.0)["report"]
        assert r["session"]["frames_ok"] == 1
        assert r["messages"][0]["id"] == 1077

    def test_crc_errors_counted(self):
        a = RtcmAnalyzer()
        a.feed(bad_crc_frame(1005), now=10.0)
        r = a.report(connected=True, now=20.0)["report"]
        assert r["session"]["crc_errors"] == 1
        assert r["session"]["frames_ok"] == 0
        verdict = r["verdict"]
        assert verdict["rtk_ready"] is False
        crc_check = next(c for c in verdict["checks"] if c["name"] == "crc")
        assert crc_check["ok"] is False

    def test_rtk_ready_positive(self):
        a = RtcmAnalyzer()
        stream = (
            make_frame(1005)
            + make_frame(1077)
            + make_frame(1087)
            + make_frame(1097)
            + make_frame(1019)
            + make_frame(1020)
            + make_frame(1045)
        )
        a.feed(stream, now=0.0)
        a.feed(stream, now=1.0)
        a.feed(stream, now=2.0)
        out = a.report(connected=True, now=30.0)
        r = out["report"]
        assert r["verdict"]["rtk_ready"] is True
        assert all(c["ok"] for c in r["verdict"]["checks"])
        # GPS/GLONASS/Galileo представлены, BeiDou нет
        assert r["constellations"]["GPS"] is True
        assert r["constellations"]["BeiDou"] is False

    def test_rtk_ready_no_ephemeris(self):
        a = RtcmAnalyzer()
        a.feed(make_frame(1005) + make_frame(1077), now=0.0)
        r = a.report(connected=True, now=1.0)["report"]
        assert r["verdict"]["rtk_ready"] is False
        eph = next(c for c in r["verdict"]["checks"] if c["name"] == "ephemerides")
        assert eph["ok"] is False

    def test_streaming_check_offline(self):
        a = RtcmAnalyzer()
        a.feed(make_frame(1005) + make_frame(1019) + make_frame(1077), now=0.0)
        r = a.report(connected=False, now=1.0)["report"]
        assert r["verdict"]["rtk_ready"] is False
        st = next(c for c in r["verdict"]["checks"] if c["name"] == "streaming")
        assert st["ok"] is False

    def test_message_stats(self):
        a = RtcmAnalyzer()
        a.feed(make_frame(1077) * 2, now=0.0)
        a.feed(make_frame(1077), now=1.0)
        r = a.report(connected=True, now=10.0)["report"]
        m = r["messages"][0]
        assert m["id"] == 1077
        assert m["name"] == "GPS MSM7"
        assert m["count"] == 3
        assert m["rate_hz"] == 0.3
        assert m["avg_size"] > 0
        assert m["last_seen"] == 9.0

    def test_junk_bytes_tracked(self):
        a = RtcmAnalyzer()
        a.feed(b"\x00\x01\x02" + make_frame(1005), now=0.0)
        r = a.report(connected=True, now=1.0)["report"]
        assert r["session"]["junk_bytes"] == 3


# ---------- hub интеграция ----------


class TestHubIntegration:
    def test_feed_and_get_analysis(self):
        """feed_rtcm из потока источника наполняет окно, get_analysis отдаёт снимок."""
        from app.ntrip.hub import NtripHub

        hub = NtripHub()
        assert hub.get_analysis("BASE1") is None  # сбор не велся
        hub.feed_rtcm("BASE1", make_frame(1005))
        hub.feed_rtcm("BASE1", make_frame(1077) + make_frame(1019))
        result = hub.get_analysis("BASE1")
        assert result is not None
        assert result["connected"] is False  # SOURCE-сессии нет
        assert result["report"]["session"]["frames_ok"] == 3
        ids = {m["id"] for m in result["report"]["messages"]}
        assert ids == {1005, 1077, 1019}

    def test_analysis_streaming_check_with_live_source(self):
        """При активной SOURCE-сессии проверка streaming должна стать ok."""
        from app.ntrip.hub import NtripHub

        hub = NtripHub()
        hub._source_sessions["BASE1:10.0.0.1:5000"] = {
            "mountpoint": "BASE1",
            "peer": "10.0.0.1:5000",
        }
        hub.feed_rtcm("BASE1", make_frame(1005) + make_frame(1077) + make_frame(1019))
        result = hub.get_analysis("BASE1")
        assert result["connected"] is True
        st = next(c for c in result["report"]["verdict"]["checks"] if c["name"] == "streaming")
        assert st["ok"] is True


# ---------- API ----------


class TestAnalysisApi:
    async def test_endpoint_flow(self):
        """GET /analysis/{mp}: 404 для несуществующего, данные для владельца, 403 для чужого."""
        import uuid
        from types import SimpleNamespace

        import bcrypt
        from app.api import monitoring
        from app.db.models import Base, SourceModel, UserModel
        from app.db.session import get_session as _orig_get_session
        from app.ntrip.hub import NtripHub
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        def fast_hash(pw: str) -> str:
            return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=4)).decode()

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sm = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        hub = NtripHub()
        hub.feed_rtcm("BASE1", make_frame(1005) + make_frame(1077) + make_frame(1019))

        app = FastAPI()
        app.include_router(monitoring.router)
        app.state.ctx = SimpleNamespace(ntrip_hub=hub, ntrip_server=None)

        async def _override_get_session():
            async with sm() as s:
                yield s

        app.dependency_overrides[_orig_get_session] = _override_get_session

        owner = UserModel(
            username="owner",
            email="owner@example.com",
            password_hash=fast_hash("longpassword123"),
            role="user",
            status="approved",
        )
        stranger = UserModel(
            username="stranger",
            email="str@example.com",
            password_hash=fast_hash("longpassword123"),
            role="user",
            status="approved",
        )
        admin = UserModel(
            username="root",
            email="root@example.com",
            password_hash=fast_hash("longpassword123"),
            role="admin",
            status="approved",
        )
        async with sm() as s:
            s.add_all([owner, stranger, admin])
            await s.commit()
            s.add(
                SourceModel(
                    id=str(uuid.uuid4()),
                    mountpoint="BASE1",
                    password=fast_hash("longpassword123"),
                    owner_id=owner.id,
                )
            )
            await s.commit()

        async def _get_as(user: UserModel) -> tuple[int, dict]:
            async def _u():
                return user

            app.dependency_overrides[monitoring.get_current_user] = _u
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                resp = await c.get("/analysis/BASE1")
                return resp.status_code, resp.json() if resp.status_code == 200 else {}

        # владелец — получает отчёт
        code, data = await _get_as(owner)
        assert code == 200
        assert data["report"]["session"]["frames_ok"] == 3
        assert data["window_s"] == 60.0

        # чужой пользователь — 403
        code, _ = await _get_as(stranger)
        assert code == 403

        # админ — разрешено
        code, data = await _get_as(admin)
        assert code == 200

        # несуществующий mountpoint — 404
        async def _u():
            return owner

        app.dependency_overrides[monitoring.get_current_user] = _u
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.get("/analysis/NOSUCH")
            assert resp.status_code == 404

        await engine.dispose()
