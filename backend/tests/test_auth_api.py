"""Тесты Auth API: register, login, logout, me (T-001, Q-001).

Покрывается реальный путь авторизации: JWT из cookie `ntrip_session` ->
get_current_user / get_optional_user -> загрузка пользователя из БД.
Хеширование подменяется быстрым bcrypt (rounds=4), проверка — реальная.

Примечание про cookie: login ставит cookie с Domain=localhost, который httpx
(следует RFC 6265) не возвращает на localhost-запросы. В тестах, где нужен
авторизованный запрос, cookie ставится в jar напрямую (без domain) — это
эквивалентно поведению браузера на localhost.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import timedelta

import bcrypt
import pytest
from app.api import auth as auth_module
from app.core.security import create_access_token
from app.db.models import Base, UserModel
from app.db.session import get_session as _orig_get_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

PASSWORD = "longpassword123"


def _fast_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()


@pytest.fixture(autouse=True)
def _clear_lockout():
    """Изоляция: rate-limit lockout — глобальное состояние, чистим между тестами."""
    from app.core import security

    security._login_attempts.clear()
    yield
    security._login_attempts.clear()


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


@pytest.fixture
def app(session: AsyncSession) -> FastAPI:
    """Приложение с РЕАЛЬНЫМИ get_current_user/get_optional_user (без override)."""
    app = FastAPI()
    app.include_router(auth_module.router, prefix="/api/auth")

    async def _override_get_session():
        yield session

    app.dependency_overrides[_orig_get_session] = _override_get_session
    # Быстрый хеш при регистрации; verify_password остаётся реальным
    auth_module.hash_password = _fast_hash
    return app


def _make_client(app: FastAPI, ip: str = "10.0.0.1") -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, client=(ip, 12345)),
        base_url="http://test",
    )


async def _make_user(
    session: AsyncSession,
    username: str = "testuser",
    email: str = "test@example.com",
    role: str = "user",
    status: str = "approved",
) -> UserModel:
    u = UserModel(
        username=username,
        email=email,
        password_hash=_fast_hash(PASSWORD),
        role=role,
        status=status,
    )
    session.add(u)
    await session.commit()
    return u


def _authed(client: AsyncClient, username: str = "testuser") -> None:
    """Симулировать браузер: JWT в cookie без domain-атрибута."""
    client.cookies.set("ntrip_session", create_access_token(username))


# ---------- register ----------


class TestRegister:
    async def test_success(self, app: FastAPI, session: AsyncSession):
        async with _make_client(app) as c:
            resp = await c.post(
                "/api/auth/register",
                json={"username": "newuser", "email": "new@example.com", "password": PASSWORD},
            )
            assert resp.status_code == 200
            assert resp.json()["ok"] is True
        # заявка создаётся в статусе pending
        user = (
            await session.execute(select(UserModel).where(UserModel.username == "newuser"))
        ).scalar_one()
        assert user.status == "pending"
        assert user.password_hash != PASSWORD  # пароль не хранится открыто

    async def test_duplicate_username(self, app: FastAPI, session: AsyncSession):
        await _make_user(session, "taken", "taken@example.com")
        async with _make_client(app) as c:
            resp = await c.post(
                "/api/auth/register",
                json={"username": "taken", "email": "other@example.com", "password": PASSWORD},
            )
            assert resp.status_code == 400
            assert "занят" in resp.json()["detail"]

    async def test_duplicate_email(self, app: FastAPI, session: AsyncSession):
        await _make_user(session, "first", "dup@example.com")
        async with _make_client(app) as c:
            resp = await c.post(
                "/api/auth/register",
                json={"username": "second", "email": "dup@example.com", "password": PASSWORD},
            )
            assert resp.status_code == 400
            assert "зарегистрирован" in resp.json()["detail"]


# ---------- login ----------


class TestLogin:
    async def test_success_sets_cookie(self, app: FastAPI, session: AsyncSession):
        await _make_user(session)
        async with _make_client(app) as c:
            resp = await c.post(
                "/api/auth/login", json={"username": "testuser", "password": PASSWORD}
            )
            assert resp.status_code == 200
            assert resp.json() == {"username": "testuser", "role": "user"}
            # cookie выставлен в Set-Cookie (без domain httpx его не сохраняет,
            # но сам факт установки проверяем по заголовку ответа)
            assert "ntrip_session=" in resp.headers["set-cookie"]
            assert "HttpOnly" in resp.headers["set-cookie"]

    async def test_login_by_email(self, app: FastAPI, session: AsyncSession):
        await _make_user(session)
        async with _make_client(app) as c:
            resp = await c.post(
                "/api/auth/login", json={"username": "test@example.com", "password": PASSWORD}
            )
            assert resp.status_code == 200

    async def test_wrong_password(self, app: FastAPI, session: AsyncSession):
        await _make_user(session)
        async with _make_client(app) as c:
            resp = await c.post(
                "/api/auth/login", json={"username": "testuser", "password": "wrongpassword"}
            )
            assert resp.status_code == 401
            assert "set-cookie" not in resp.headers

    async def test_unknown_user(self, app: FastAPI):
        async with _make_client(app) as c:
            resp = await c.post(
                "/api/auth/login", json={"username": "ghost", "password": PASSWORD}
            )
            assert resp.status_code == 401

    async def test_pending_user_denied(self, app: FastAPI, session: AsyncSession):
        await _make_user(session, username="pend", email="pend@example.com", status="pending")
        async with _make_client(app) as c:
            resp = await c.post(
                "/api/auth/login", json={"username": "pend", "password": PASSWORD}
            )
            assert resp.status_code == 401

    async def test_blocked_user_denied(self, app: FastAPI, session: AsyncSession):
        await _make_user(session, username="blk", email="blk@example.com", status="blocked")
        async with _make_client(app) as c:
            resp = await c.post(
                "/api/auth/login", json={"username": "blk", "password": PASSWORD}
            )
            assert resp.status_code == 401

    async def test_lockout_after_max_attempts(self, app: FastAPI, session: AsyncSession):
        """5 неудач с одного IP -> 429 даже с верным паролем (README: 5/5 мин)."""
        await _make_user(session)
        async with _make_client(app, ip="203.0.113.7") as c:
            for _ in range(5):
                resp = await c.post(
                    "/api/auth/login", json={"username": "testuser", "password": "wrongpassword"}
                )
                assert resp.status_code == 401
            resp = await c.post(
                "/api/auth/login", json={"username": "testuser", "password": PASSWORD}
            )
            assert resp.status_code == 429

    async def test_lockout_is_per_ip(self, app: FastAPI, session: AsyncSession):
        await _make_user(session)
        async with _make_client(app, ip="203.0.113.8") as c1:
            for _ in range(5):
                await c1.post(
                    "/api/auth/login", json={"username": "testuser", "password": "wrongpassword"}
                )
            blocked = await c1.post(
                "/api/auth/login", json={"username": "testuser", "password": PASSWORD}
            )
            assert blocked.status_code == 429
        # другой IP не заблокирован
        async with _make_client(app, ip="203.0.113.9") as c2:
            ok = await c2.post(
                "/api/auth/login", json={"username": "testuser", "password": PASSWORD}
            )
            assert ok.status_code == 200


# ---------- logout ----------


class TestLogout:
    async def test_cookie_removed(self, app: FastAPI):
        async with _make_client(app) as c:
            _authed(c)
            resp = await c.post("/api/auth/logout")
            assert resp.status_code == 200
            assert resp.json()["ok"] is True
            # cookie удалён (пустое значение + expires в прошлом)
            sc = resp.headers["set-cookie"]
            assert "ntrip_session=" in sc
            assert "Max-Age=0" in sc or "Expires" in sc
            me = await c.get("/api/auth/me")
            assert me.status_code == 401


# ---------- me ----------


class TestMe:
    async def test_with_valid_cookie(self, app: FastAPI, session: AsyncSession):
        await _make_user(session)
        async with _make_client(app) as c:
            _authed(c)
            resp = await c.get("/api/auth/me")
            assert resp.status_code == 200
            data = resp.json()
            assert data["username"] == "testuser"
            assert data["email"] == "test@example.com"
            assert data["role"] == "user"
            assert data["status"] == "approved"
            assert data["quotas"]["sources"] == 10  # дефолт модели
            assert data["can_record"] is True

    async def test_anonymous_401(self, app: FastAPI):
        async with _make_client(app) as c:
            resp = await c.get("/api/auth/me")
            assert resp.status_code == 401

    async def test_garbage_token_401(self, app: FastAPI):
        async with _make_client(app) as c:
            c.cookies.set("ntrip_session", "not.a.jwt")
            resp = await c.get("/api/auth/me")
            assert resp.status_code == 401

    async def test_valid_token_unknown_user_401(self, app: FastAPI):
        async with _make_client(app) as c:
            c.cookies.set("ntrip_session", create_access_token("deleted-user"))
            resp = await c.get("/api/auth/me")
            assert resp.status_code == 401

    async def test_valid_token_blocked_user_401(self, app: FastAPI, session: AsyncSession):
        await _make_user(session, username="blk", email="blk@example.com", status="blocked")
        async with _make_client(app) as c:
            _authed(c, "blk")
            resp = await c.get("/api/auth/me")
            assert resp.status_code == 401

    async def test_expired_token_401(self, app: FastAPI, session: AsyncSession):
        await _make_user(session)
        async with _make_client(app) as c:
            c.cookies.set(
                "ntrip_session",
                create_access_token("testuser", expires_delta=timedelta(minutes=-1)),
            )
            resp = await c.get("/api/auth/me")
            assert resp.status_code == 401
