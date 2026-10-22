"""Асинхронная сессия БД."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models import Base

engine = create_async_engine(settings.database_url, echo=settings.debug)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Зависимость FastAPI: выдаёт сессию БД на время запроса."""
    async with async_session() as session:
        yield session


# Для кода вне FastAPI-запросов (NTRIP hub и т. п.): async with session_scope() as s:
session_scope = async_session


async def init_db() -> None:
    """Создать все таблицы (для dev-режима)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Закрыть все сессии и движок."""
    await engine.dispose()
