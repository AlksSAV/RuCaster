"""Тесты T-012: квота источников при создании mountpoint.

Хеширование пароля подменяется быстрым bcrypt-хелпером (passlib 1.7.4
несовместим с bcrypt 5.x).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import bcrypt
import pytest
from app.api.sources import router as sources_router
from app.db.models import Base, SourceModel, UserModel
from app.db.session import get_session as _orig_get_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _fast_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()


# ---------- helpers ----------


def _make_user(session: AsyncSession, quotas: int, username: str = "qt") -> UserModel:
    u = UserModel(
        username=username,
        email=f"{username}@example.com",
        password_hash=_fast_hash("longpassword123"),
        role="user",
        status="approved",
        quotas_sources=quotas,
    )
    session.add(u)
    return u


def _make_sources(session: AsyncSession, owner_id: str, mountpoints: list[str]) -> None:
    for mp in mountpoints:
        session.add(
            SourceModel(
                id=str(uuid.uuid4()),
                mountpoint=mp,
                password=_fast_hash("longpassword123"),
                owner_id=owner_id,
            )
        )


# ---------- fixtures ----------


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    s = sm()
    yield s
    await s.close()
    await engine.dispose()


def _make_app(session: AsyncSession, user: UserModel) -> FastAPI:
    app = FastAPI()
    app.include_router(sources_router, prefix="/api/sources")

    # Переопределяем зависимость get_session — отдаём тестовую сессию
    async def _override_get_session():
        yield session

    app.dependency_overrides[_orig_get_session] = _override_get_session

    # Переопределяем get_optional_user — отдаём тестового пользователя
    async def _override_user():
        return user

    # get_optional_user импортируется в sources.py через auth.py,
    # где он используется в Depends. Заменяем по имени.
    from app.api.auth import get_optional_user

    app.dependency_overrides[get_optional_user] = _override_user

    # Подменяем хеш-хелпер
    import app.api.sources as sm

    sm.hash_password = _fast_hash

    return app


async def _post_source(app: FastAPI, mountpoint: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.post(
            "/api/sources",
            json={"mountpoint": mountpoint, "password": "longpassword123"},
        )


# ---------- tests ----------


class TestQuotaEnforcement:
    async def test_creation_allowed_under_quota(self, session):
        user = _make_user(session, quotas=3)
        await session.commit()
        await session.refresh(user)
        _make_sources(session, user.id, ["mp0"])
        await session.commit()

        app = _make_app(session, user)
        resp = await _post_source(app, "mp_new")
        assert resp.status_code == 201
        assert resp.json()["mountpoint"] == "mp_new"

    async def test_creation_forbidden_at_quota(self, session):
        user = _make_user(session, quotas=2)
        await session.commit()
        await session.refresh(user)
        _make_sources(session, user.id, ["mp0", "mp1"])
        await session.commit()

        app = _make_app(session, user)
        resp = await _post_source(app, "mp_over")
        assert resp.status_code == 403
        detail = resp.json()["detail"].lower()
        assert "квота" in detail or "quota" in detail

    async def test_quota_counts_only_own_sources(self, session):
        user = _make_user(session, quotas=1)
        await session.commit()
        await session.refresh(user)

        other = UserModel(
            username="other",
            email="other@example.com",
            password_hash=_fast_hash("longpassword123"),
            role="user",
            status="approved",
            quotas_sources=5,
        )
        session.add(other)
        await session.commit()
        _make_sources(session, other.id, ["foreign0"])
        await session.commit()

        app = _make_app(session, user)
        resp = await _post_source(app, "mine0")
        assert resp.status_code == 201

    async def test_zero_quota_blocks_creation(self, session):
        user = _make_user(session, quotas=0)
        await session.commit()
        await session.refresh(user)

        app = _make_app(session, user)
        resp = await _post_source(app, "any")
        assert resp.status_code == 403


class TestQuotaOrdering:
    async def test_duplicate_mountpoint_checked_before_quota(self, session):
        user = _make_user(session, quotas=1)
        await session.commit()
        await session.refresh(user)
        _make_sources(session, user.id, ["mp_taken"])
        await session.commit()

        app = _make_app(session, user)
        resp = await _post_source(app, "mp_taken")
        assert resp.status_code == 400
        assert "существует" in resp.json()["detail"]
