"""Безопасность: хеширование, JWT, rate-limit."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Кэш блокировки входа: {ip: {"attempts": int, "locked_until": float}}
_login_attempts: dict[str, dict] = {}


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    return jwt.encode(
        {"sub": subject, "exp": expire},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def check_login_lockout(ip: str) -> bool:
    """Возвращает True если вход разрешён, False если заблокирован."""
    entry = _login_attempts.get(ip)
    if entry and time.time() < entry["locked_until"]:
        return False
    if entry:
        entry["attempts"] = 0
    return True


def record_login_attempt(ip: str, success: bool) -> None:
    if ip not in _login_attempts:
        _login_attempts[ip] = {"attempts": 0, "locked_until": 0.0}
    entry = _login_attempts[ip]
    if not success:
        entry["attempts"] += 1
        if entry["attempts"] >= settings.max_login_attempts:
            entry["locked_until"] = time.time() + settings.login_lockout_seconds
