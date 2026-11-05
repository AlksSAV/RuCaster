"""Admin API: управление пользователями и настройками."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.models import SourceModel, UserModel
from app.db.schemas import UserCanRecordPatch, UserQuotaPatch, UserResponse
from app.db.session import get_session

router = APIRouter()


async def require_admin(user: UserModel = Depends(get_current_user)) -> UserModel:
    """Зависимость: пропускает только роль admin (иначе 403)."""
    if user.role != "admin":
        raise HTTPException(403, "требуются права администратора")
    return user


def _as_response(u: UserModel) -> UserResponse:
    return UserResponse(
        username=u.username,
        email=u.email,
        role=u.role,
        status=u.status,
        quotas={
            "sources": u.quotas_sources or 0,
            "substitutions": u.quotas_substitutions or 0,
        },
        can_record=bool(u.can_record),
        created_at=u.created_at,
    )


async def _get_user_or_404(username: str, session: AsyncSession) -> UserModel:
    stmt = select(UserModel).where(UserModel.username == username)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "пользователь не найден")
    return user


async def _ensure_no_sources(user: UserModel, session: AsyncSession) -> None:
    """Удаление пользователя допустимо только когда у него нет источников."""
    stmt = (
        select(func.count())
        .select_from(SourceModel)
        .where(SourceModel.owner_id == user.id)
    )
    count = (await session.execute(stmt)).scalar_one()
    if count:
        raise HTTPException(
            409,
            f"у пользователя {count} источников — сначала удалите их",
        )


@router.get("", response_model=list[UserResponse])
async def list_users(
    session: AsyncSession = Depends(get_session),
    admin: UserModel = Depends(require_admin),
):
    """Список всех пользователей."""
    stmt = select(UserModel).order_by(UserModel.created_at)
    users = (await session.execute(stmt)).scalars().all()
    return [_as_response(u) for u in users]


@router.post("/{username}/approve", response_model=UserResponse)
async def approve_user(
    username: str,
    session: AsyncSession = Depends(get_session),
    admin: UserModel = Depends(require_admin),
):
    """Одобрить регистрацию (pending -> approved)."""
    user = await _get_user_or_404(username, session)
    if user.status != "pending":
        raise HTTPException(400, f"ожидает одобрения только pending, сейчас: {user.status}")
    user.status = "approved"
    await session.commit()
    return _as_response(user)


@router.post("/{username}/reject", response_model=dict)
async def reject_user(
    username: str,
    session: AsyncSession = Depends(get_session),
    admin: UserModel = Depends(require_admin),
):
    """Отклонить регистрацию (удалить заявку)."""
    user = await _get_user_or_404(username, session)
    if user.username == admin.username:
        raise HTTPException(400, "нельзя отклонить собственную учётную запись")
    await _ensure_no_sources(user, session)
    await session.delete(user)
    await session.commit()
    return {"ok": True}


@router.post("/{username}/block", response_model=UserResponse)
async def block_user(
    username: str,
    session: AsyncSession = Depends(get_session),
    admin: UserModel = Depends(require_admin),
):
    """Заблокировать пользователя."""
    user = await _get_user_or_404(username, session)
    if user.username == admin.username:
        raise HTTPException(400, "нельзя заблокировать собственную учётную запись")
    user.status = "blocked"
    await session.commit()
    return _as_response(user)


@router.post("/{username}/unblock", response_model=UserResponse)
async def unblock_user(
    username: str,
    session: AsyncSession = Depends(get_session),
    admin: UserModel = Depends(require_admin),
):
    """Разблокировать пользователя (blocked -> approved)."""
    user = await _get_user_or_404(username, session)
    if user.status != "blocked":
        raise HTTPException(400, f"заблокирован только blocked, сейчас: {user.status}")
    user.status = "approved"
    await session.commit()
    return _as_response(user)


@router.delete("/{username}", response_model=dict)
async def delete_user(
    username: str,
    session: AsyncSession = Depends(get_session),
    admin: UserModel = Depends(require_admin),
):
    """Удалить пользователя (источники должны быть удалены заранее)."""
    user = await _get_user_or_404(username, session)
    if user.username == admin.username:
        raise HTTPException(400, "нельзя удалить собственную учётную запись")
    await _ensure_no_sources(user, session)
    await session.delete(user)
    await session.commit()
    return {"ok": True}


@router.patch("/{username}/quota", response_model=UserResponse)
async def patch_quota(
    username: str,
    patch: UserQuotaPatch,
    session: AsyncSession = Depends(get_session),
    admin: UserModel = Depends(require_admin),
):
    """Изменить квоты пользователя (обновляются только переданные поля)."""
    user = await _get_user_or_404(username, session)
    if patch.quotas_sources is not None:
        user.quotas_sources = patch.quotas_sources
    if patch.quotas_substitutions is not None:
        user.quotas_substitutions = patch.quotas_substitutions
    await session.commit()
    return _as_response(user)


@router.post("/{username}/can-record", response_model=UserResponse)
async def set_can_record(
    username: str,
    patch: UserCanRecordPatch,
    session: AsyncSession = Depends(get_session),
    admin: UserModel = Depends(require_admin),
):
    """Разрешить/запретить запись."""
    user = await _get_user_or_404(username, session)
    user.can_record = patch.can_record
    await session.commit()
    return _as_response(user)
