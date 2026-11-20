"""Тесты безопасности: права на удаление источников.

Покрытие: delete_source — проверка owner_id и роли admin.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import bcrypt
import pytest
from app.api.auth import get_current_user, get_optional_user
from app.api.sources import router as sources_router
from app.db.models import Base, SourceModel, UserModel
from app.db.session import get_session as _orig_get_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _fast_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()


# ---------- helpers ----------


def _make_user(
    session: AsyncSession,
    username: str = "tuser",
    role: str = "user",
    quotas: int = 5,
) -> UserModel:
    u = UserModel(
        username=username,
        email=f"{username}@example.com",
        password_hash=_fast_hash("longpassword123"),
        role=role,
        status="approved",
        quotas_sources=quotas,
    )
    session.add(u)
    return u


def _make_source(
    session: AsyncSession,
    mountpoint: str,
    owner_id: str,
) -> None:
    session.add(
        SourceModel(
            id=str(uuid.uuid4()),
            mountpoint=mountpoint,
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

    async def _override_get_session():
        yield session

    app.dependency_overrides[_orig_get_session] = _override_get_session
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user

    import app.api.sources as sm

    sm.hash_password = _fast_hash

    return app


# ---------- tests ----------


class TestDeleteSourceAuth:
    """Удаление источника требует авторизации (любой 401)."""

    async def test_unauthorized_cannot_delete(self, session):
        user = _make_user(session)
        await session.commit()
        _make_source(session, "test", user.id)
        await session.commit()

        app = FastAPI()
        app.include_router(sources_router, prefix="/api/sources")
        app.dependency_overrides[_orig_get_session] = lambda: session

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.delete("/api/sources/test")
            assert resp.status_code == 401


class TestDeleteSourceOwner:
    """Владелец может удалить свой источник."""

    async def test_owner_can_delete_own_source(self, session):
        user = _make_user(session, username="owner")
        await session.commit()
        await session.refresh(user)
        _make_source(session, "owner_mp", user.id)
        await session.commit()

        app = _make_app(session, user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.delete("/api/sources/owner_mp")
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}

        # Проверить, что источник удалён
        result = await session.execute(
            select(SourceModel).where(SourceModel.mountpoint == "owner_mp")
        )
        assert result.scalar_one_or_none() is None

    async def test_owner_cannot_delete_foreign_source(self, session):
        owner = _make_user(session, username="owner")
        victim = _make_user(session, username="victim")
        await session.commit()
        await session.refresh(owner)
        await session.refresh(victim)

        _make_source(session, "owner_mp", owner.id)
        await session.commit()

        app = _make_app(session, victim)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.delete("/api/sources/owner_mp")
            assert resp.status_code == 403

    async def test_delete_nonexistent_returns_404(self, session):
        user = _make_user(session)
        await session.commit()

        app = _make_app(session, user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.delete("/api/sources/no_such_mp")
            assert resp.status_code == 404


class TestDeleteSourceAdmin:
    """Admin может удалить чужой источник."""

    async def test_admin_can_delete_any_source(self, session):
        owner = _make_user(session, username="owner")
        admin = _make_user(session, username="admin", role="admin")
        await session.commit()
        await session.refresh(owner)
        await session.refresh(admin)

        _make_source(session, "owner_mp", owner.id)
        await session.commit()

        app = _make_app(session, admin)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.delete("/api/sources/owner_mp")
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}

    async def test_admin_can_delete_own_source(self, session):
        admin = _make_user(session, username="admin", role="admin")
        await session.commit()
        await session.refresh(admin)

        _make_source(session, "admin_mp", admin.id)
        await session.commit()

        app = _make_app(session, admin)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.delete("/api/sources/admin_mp")
            assert resp.status_code == 200
