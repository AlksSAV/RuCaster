"""Auth API: login, register, logout, me."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    check_login_lockout,
    create_access_token,
    decode_access_token,
    hash_password,
    record_login_attempt,
    verify_password,
)
from app.db.models import UserModel
from app.db.schemas import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserResponse,
)
from app.db.session import get_session

log = logging.getLogger("rucaster.api.auth")
router = APIRouter()


async def get_optional_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> UserModel | None:
    """Как get_current_user, но для анонимных запросов возвращает None вместо 401."""
    token = request.cookies.get("ntrip_session")
    if not token:
        return None
    username = decode_access_token(token)
    if not username:
        return None
    stmt = select(UserModel).where(UserModel.username == username)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user or user.status != "approved":
        return None
    return user


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> UserModel:
    """Зависимость: пользователь из cookie `ntrip_session` (JWT)."""
    user = await get_optional_user(request, session)
    if user is None:
        raise HTTPException(401, "не авторизован")
    return user


@router.post("/login", response_model=LoginResponse)
async def login(
    req: LoginRequest,
    response: Response,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    ip = request.client.host if request.client else "unknown"

    if not check_login_lockout(ip):
        raise HTTPException(429, "Слишком много попыток. Подождите.")

    stmt = select(UserModel).where(
        (UserModel.username == req.username) | (UserModel.email == req.username)
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.password_hash):
        record_login_attempt(ip, False)
        raise HTTPException(401, "неверный логин/пароль или аккаунт не одобрен")

    if user.status != "approved":
        record_login_attempt(ip, False)
        raise HTTPException(401, "неверный логин/пароль или аккаунт не одобрен")

    record_login_attempt(ip, True)
    token = create_access_token(user.username)

    response.set_cookie(
        key="ntrip_session",
        value=token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,
        path="/",
        samesite="lax",
    )

    return LoginResponse(username=user.username, role=user.role)


@router.post("/register")
async def register(
    req: RegisterRequest,
    session: AsyncSession = Depends(get_session),
):
    # Проверяем уникальность
    stmt1 = select(UserModel).where(UserModel.username == req.username)
    stmt2 = select(UserModel).where(UserModel.email == req.email)
    if (await session.execute(stmt1)).scalar_one_or_none():
        raise HTTPException(400, "username уже занят")
    if (await session.execute(stmt2)).scalar_one_or_none():
        raise HTTPException(400, "email уже зарегистрирован")

    user = UserModel(
        username=req.username,
        email=req.email,
        password_hash=hash_password(req.password),
        status="pending",
    )
    session.add(user)
    await session.commit()
    log.info("Registration: %s (pending approval)", req.username)
    return {"ok": True, "message": "Заявка отправлена на одобрение админу"}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("ntrip_session", path="/")
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
async def me(user: UserModel = Depends(get_current_user)):
    return UserResponse(
        username=user.username,
        email=user.email,
        role=user.role,
        status=user.status,
        quotas={
            "sources": user.quotas_sources or 0,
            "substitutions": user.quotas_substitutions or 0,
        },
        can_record=bool(user.can_record),
        created_at=user.created_at,
    )
