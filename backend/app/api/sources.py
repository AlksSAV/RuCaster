"""Sources API: CRUD источников (баз)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_optional_user
from app.db.models import SourceModel, UserModel
from app.db.schemas import SourceCreate, SourceFullResponse, SourceResponse
from app.db.session import get_session

router = APIRouter()


@router.get("", response_model=list[SourceResponse])
async def list_sources(
    session: AsyncSession = Depends(get_session),
    user: UserModel | None = Depends(get_optional_user),
):
    """Получить список всех источников."""
    stmt = select(SourceModel).order_by(SourceModel.mountpoint)
    result = await session.execute(stmt)
    sources = result.scalars().all()
    owner_id = user.id if user else None
    return [
        SourceResponse(
            id=s.id,
            mountpoint=s.mountpoint,
            connected=False,
            owner=s.owner_id,
            mine=(s.owner_id == owner_id),
            editable=(s.owner_id == owner_id),
        )
        for s in sources
    ]


@router.post("", response_model=SourceFullResponse, status_code=201)
async def create_source(
    req: SourceCreate,
    session: AsyncSession = Depends(get_session),
    user: UserModel = Depends(get_optional_user),
):
    """Создать новый источник (базу)."""
    # Если пользователь не авторизован — остаёмся на "demo-owner",
    # чтобы публичный доступ не падал, но в реальности ожидается JWT.
    owner_id = user.id if user else "demo-owner"

    stmt = select(SourceModel).where(SourceModel.mountpoint == req.mountpoint)
    if (await session.execute(stmt)).scalar_one_or_none():
        raise HTTPException(400, "mountpoint уже существует")

    source = SourceModel(
        id=str(uuid.uuid4()),
        mountpoint=req.mountpoint,
        password=req.password,
        owner_id=owner_id,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return SourceFullResponse(
        id=source.id,
        mountpoint=source.mountpoint,
        connected=False,
        owner=source.owner_id,
        mine=True,
        editable=True,
    )


@router.delete("/{mountpoint}")
async def delete_source(mountpoint: str, session: AsyncSession = Depends(get_session)):
    """Удалить источник."""
    # TODO: проверка прав владельца/admin
    stmt = select(SourceModel).where(SourceModel.mountpoint == mountpoint)
    result = await session.execute(stmt)
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, "источник не найден")

    await session.delete(source)
    await session.commit()
    return {"ok": True}
