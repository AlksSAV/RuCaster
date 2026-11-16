"""Безопасность: хеширование, JWT, rate-limit."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Кэш блокировки входа: {ip: {"attempts": int, "first_at": float, "locked_until": float}}
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


def decode_access_token(token: str) -> str | None:
    """Вернуть subject из валидного JWT, иначе None (в т.ч. просроченного)."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None


def check_login_lockout(ip: str) -> bool:
    """Возвращает True если вход разрешён, False если IP заблокирован."""
    entry = _login_attempts.get(ip)
    if not entry:
        return True
    return time.time() >= entry["locked_until"]


def record_login_attempt(ip: str, success: bool) -> None:
    now = time.time()
    if success:
        _login_attempts.pop(ip, None)
        return
    entry = _login_attempts.get(ip)
    if entry is None:
        entry = {"attempts": 0, "first_at": now, "locked_until": 0.0}
        _login_attempts[ip] = entry
    elif now - entry["first_at"] > settings.login_lockout_seconds:
        # Окно неудач истекло — считаем заново
        entry["attempts"] = 0
        entry["first_at"] = now
    entry["attempts"] += 1
    if entry["attempts"] >= settings.max_login_attempts:
        entry["locked_until"] = now + settings.login_lockout_seconds
