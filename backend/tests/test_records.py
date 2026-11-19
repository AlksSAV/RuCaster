"""Тесты T-007: запись статики (RecordManager + API)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import bcrypt
import pytest
from app.api.auth import get_current_user
from app.api.records import router as records_router
from app.db.models import Base, SourceModel, UserModel
from app.db.session import get_session as _orig_get_session
from app.ntrip.hub import NtripHub
from app.services.recorder import FILE_RE, RecordManager, safe_mountpoint
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _fast_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()


def _manager(tmp_path, hub: NtripHub | None = None) -> RecordManager:
    return RecordManager(
        hub=hub or NtripHub(),
        root=tmp_path,
        retention_days=3,
        default_duration=8 * 3600,
        max_duration=24 * 3600,
    )


# ---------- RecordManager ----------


class TestRecordManager:
    async def test_feed_writes_file_and_stops(self, tmp_path):
        hub = NtripHub()
        mgr = _manager(tmp_path, hub)
        rec = mgr.start("BASE1", owner="owner", duration=3600)
        hub._feed_sinks("BASE1", b"\xd3\x00\x00payload")

        await mgr.stop(rec.id)
        assert rec.alive is False
        assert rec.id not in mgr.records
        assert rec.bytes_total == 10
        assert rec.file_path is not None
        assert rec.file_path.read_bytes() == b"\xd3\x00\x00payload"
        # sink снят с hub
        assert hub._sinks.get("BASE1") in (None, [])

    async def test_stop_unknown_returns_false(self, tmp_path):
        mgr = _manager(tmp_path)
        assert await mgr.stop(str(uuid.uuid4())) is False

    async def test_duration_expires_recording(self, tmp_path):
        import asyncio

        mgr = _manager(tmp_path)
        rec = mgr.start("BASE1", owner="owner", duration=0)
        # duration=0 — без ограничения по времени; проверим явную остановку
        await asyncio.sleep(0)
        assert rec.alive is True
        await mgr.stop(rec.id)
        assert rec.alive is False

    async def test_files_and_disk_info(self, tmp_path):
        mgr = _manager(tmp_path)
        directory = tmp_path / "BASE1"
        directory.mkdir()
        (directory / "20260101_1200.rtcm").write_bytes(b"x" * 10)
        (directory / "20260102_1200.rtcm").write_bytes(b"y" * 5)
        (directory / "ignore.txt").write_bytes(b"z")

        files = mgr.files("BASE1")
        assert [f["name"] for f in files] == ["20260102_1200.rtcm", "20260101_1200.rtcm"]
        assert files[0]["bytes"] == 5

        info = mgr.disk_info()
        assert info["total_bytes"] == 15
        assert info["mountpoints"] == [{"mountpoint": "BASE1", "bytes": 15, "files": 2}]
        assert info["free_bytes"] > 0

    def test_files_missing_dir(self, tmp_path):
        mgr = _manager(tmp_path)
        assert mgr.files("NOPE") == []
        assert mgr.day_files("NOPE", "20260101") == []

    def test_safe_mountpoint(self):
        assert safe_mountpoint("BASE1") == "BASE1"
        assert safe_mountpoint("../etc/passwd") == ".._etc_passwd"
        assert safe_mountpoint("a b") == "a_b"

    def test_file_re(self):
        assert FILE_RE.match("20260101_1200.rtcm")
        assert not FILE_RE.match("20260101_1200.zip")
        assert not FILE_RE.match("../20260101_1200.rtcm")


class TestRetention:
    def test_purge_old_files(self, tmp_path):
        mgr = _manager(tmp_path)
        directory = tmp_path / "BASE1"
        directory.mkdir()
        today = datetime.now(UTC).date()
        fresh = directory / f"{today:%Y%m%d}_1200.rtcm"
        old_day = today - timedelta(days=5)
        old = directory / f"{old_day:%Y%m%d}_1200.rtcm"
        fresh.write_bytes(b"a")
        old.write_bytes(b"b")

        removed = mgr.purge_expired()
        assert removed == 1
        assert fresh.exists()
        assert not old.exists()

    def test_purge_keeps_files_within_retention(self, tmp_path):
        mgr = _manager(tmp_path)
        directory = tmp_path / "BASE1"
        directory.mkdir()
        day = datetime.now(UTC).date() - timedelta(days=2)
        kept = directory / f"{day:%Y%m%d}_1200.rtcm"
        kept.write_bytes(b"a")

        assert mgr.purge_expired() == 0
        assert kept.exists()

    def test_purge_removes_empty_dir(self, tmp_path):
        mgr = _manager(tmp_path)
        directory = tmp_path / "OLD"
        directory.mkdir()
        day = datetime.now(UTC).date() - timedelta(days=10)
        (directory / f"{day:%Y%m%d}_1200.rtcm").write_bytes(b"a")

        assert mgr.purge_expired() == 1
        assert not directory.exists()

    def test_purge_ignores_foreign_names(self, tmp_path):
        mgr = _manager(tmp_path)
        directory = tmp_path / "BASE1"
        directory.mkdir()
        keep = directory / "notes.txt"
        keep.write_bytes(b"a")
        assert mgr.purge_expired() == 0
        assert keep.exists()


# ---------- API ----------


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with sm() as s:
        yield s
    await engine.dispose()


async def _seed(session: AsyncSession) -> dict[str, UserModel]:
    owner = UserModel(
        username="owner",
        email="owner@example.com",
        password_hash=_fast_hash("longpassword123"),
        role="user",
        status="approved",
        can_record=True,
    )
    stranger = UserModel(
        username="stranger",
        email="str@example.com",
        password_hash=_fast_hash("longpassword123"),
        role="user",
        status="approved",
        can_record=True,
    )
    admin = UserModel(
        username="root",
        email="root@example.com",
        password_hash=_fast_hash("longpassword123"),
        role="admin",
        status="approved",
    )
    session.add_all([owner, stranger, admin])
    await session.commit()
    session.add(
        SourceModel(
            id=str(uuid.uuid4()),
            mountpoint="BASE1",
            password=_fast_hash("longpassword123"),
            owner_id=owner.id,
        )
    )
    await session.commit()
    return {"owner": owner, "stranger": stranger, "admin": admin}


def _app(session: AsyncSession, manager: RecordManager, user: UserModel) -> FastAPI:
    app = FastAPI()
    app.include_router(records_router, prefix="/api/record")
    app.state.ctx = SimpleNamespace(record_manager=manager)

    async def _override_session():
        yield session

    app.dependency_overrides[_orig_get_session] = _override_session

    async def _override_user():
        return user

    app.dependency_overrides[get_current_user] = _override_user
    return app


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


class TestRecordsApi:
    async def test_start_list_stop_flow(self, session, tmp_path):
        users = await _seed(session)
        hub = NtripHub()
        mgr = _manager(tmp_path, hub)
        app = _app(session, mgr, users["owner"])

        async with await _client(app) as c:
            resp = await c.post("/api/record/BASE1", json={"duration": 600})
            assert resp.status_code == 200
            body = resp.json()
            assert body["mountpoint"] == "BASE1"
            assert body["owner"] == "owner"
            assert body["duration"] == 600
            rec_id = body["id"]

            hub._feed_sinks("BASE1", b"rtcm")
            listing = await c.get("/api/record")
            assert listing.status_code == 200
            data = listing.json()
            assert len(data["recording"]) == 1
            assert data["recording"][0]["alive"] is True
            assert data["defaults"]["retention_days"] == 3

            stop = await c.delete(f"/api/record/{rec_id}")
            assert stop.status_code == 200
            assert mgr.records == {}

    async def test_start_unknown_mountpoint(self, session, tmp_path):
        users = await _seed(session)
        app = _app(session, _manager(tmp_path), users["owner"])
        async with await _client(app) as c:
            resp = await c.post("/api/record/NOPE", json={"duration": 60})
            assert resp.status_code == 404

    async def test_start_foreign_forbidden(self, session, tmp_path):
        users = await _seed(session)
        app = _app(session, _manager(tmp_path), users["stranger"])
        async with await _client(app) as c:
            resp = await c.post("/api/record/BASE1", json={"duration": 60})
            assert resp.status_code == 403

    async def test_start_without_can_record(self, session, tmp_path):
        users = await _seed(session)
        users["owner"].can_record = False
        await session.commit()
        app = _app(session, _manager(tmp_path), users["owner"])
        async with await _client(app) as c:
            resp = await c.post("/api/record/BASE1", json={"duration": 60})
            assert resp.status_code == 403

    async def test_duration_over_max(self, session, tmp_path):
        users = await _seed(session)
        app = _app(session, _manager(tmp_path), users["owner"])
        async with await _client(app) as c:
            resp = await c.post("/api/record/BASE1", json={"duration": 10**6})
            assert resp.status_code == 400

    async def test_duplicate_recording_conflict(self, session, tmp_path):
        users = await _seed(session)
        mgr = _manager(tmp_path)
        app = _app(session, mgr, users["owner"])
        async with await _client(app) as c:
            first = await c.post("/api/record/BASE1", json={"duration": 600})
            assert first.status_code == 200
            second = await c.post("/api/record/BASE1", json={"duration": 600})
            assert second.status_code == 409
            await c.delete(f"/api/record/{first.json()['id']}")

    async def test_stop_foreign_forbidden(self, session, tmp_path):
        users = await _seed(session)
        mgr = _manager(tmp_path)
        rec = mgr.start("BASE1", owner="owner", duration=600)

        app = _app(session, mgr, users["stranger"])
        async with await _client(app) as c:
            resp = await c.delete(f"/api/record/{rec.id}")
            assert resp.status_code == 403
            missing = await c.delete(f"/api/record/{uuid.uuid4()}")
            assert missing.status_code == 404
        await mgr.stop(rec.id)

    async def test_admin_can_stop(self, session, tmp_path):
        users = await _seed(session)
        mgr = _manager(tmp_path)
        rec = mgr.start("BASE1", owner="owner", duration=600)
        app = _app(session, mgr, users["admin"])
        async with await _client(app) as c:
            resp = await c.delete(f"/api/record/{rec.id}")
            assert resp.status_code == 200
        assert rec.alive is False

    async def test_files_download_and_zip(self, session, tmp_path):
        users = await _seed(session)
        mgr = _manager(tmp_path)
        directory = tmp_path / "BASE1"
        directory.mkdir()
        (directory / "20260101_1200.rtcm").write_bytes(b"aaaa")
        (directory / "20260101_1300.rtcm").write_bytes(b"bb")
        (directory / "20260102_1200.rtcm").write_bytes(b"c")

        app = _app(session, mgr, users["owner"])
        async with await _client(app) as c:
            listing = await c.get("/api/record/BASE1")
            assert listing.status_code == 200
            assert len(listing.json()["files"]) == 3

            file_resp = await c.get("/api/record/BASE1/20260101_1200.rtcm")
            assert file_resp.status_code == 200
            assert file_resp.content == b"aaaa"

            zip_resp = await c.get("/api/record/BASE1/day/20260101")
            assert zip_resp.status_code == 200
            assert zip_resp.headers["content-type"] == "application/zip"
            assert zip_resp.content[:2] == b"PK"

    async def test_download_rejects_bad_name(self, session, tmp_path):
        users = await _seed(session)
        app = _app(session, _manager(tmp_path), users["owner"])
        async with await _client(app) as c:
            resp = await c.get("/api/record/BASE1/..%2Fsecret.rtcm")
            assert resp.status_code in (400, 404)

    async def test_day_archive_validation(self, session, tmp_path):
        users = await _seed(session)
        app = _app(session, _manager(tmp_path), users["owner"])
        async with await _client(app) as c:
            bad = await c.get("/api/record/BASE1/day/2026-01-01")
            assert bad.status_code == 400
            empty = await c.get("/api/record/BASE1/day/20260101")
            assert empty.status_code == 404

    async def test_foreign_files_forbidden(self, session, tmp_path):
        users = await _seed(session)
        app = _app(session, _manager(tmp_path), users["stranger"])
        async with await _client(app) as c:
            assert (await c.get("/api/record/BASE1")).status_code == 403
            assert (await c.get("/api/record/BASE1/day/20260101")).status_code == 403

    async def test_missing_manager(self, session, tmp_path):
        users = await _seed(session)
        app = _app(session, _manager(tmp_path), users["owner"])
        app.state.ctx = SimpleNamespace(record_manager=None)
        async with await _client(app) as c:
            assert (await c.get("/api/record")).status_code == 503
