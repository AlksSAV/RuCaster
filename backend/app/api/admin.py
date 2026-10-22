"""Admin API: управление пользователями и настройками."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db.schemas import UserCanRecordPatch, UserQuotaPatch

router = APIRouter()


@router.get("")
async def list_users():
    """Список пользователей (только admin)."""
    # TODO: вернуть всех пользователей
    raise HTTPException(501, "not implemented")


@router.post("/{username}/approve")
async def approve_user(username: str):
    """Одобрить регистрацию."""
    raise HTTPException(501, "not implemented")


@router.post("/{username}/reject")
async def reject_user(username: str):
    """Отклонить регистрацию."""
    raise HTTPException(501, "not implemented")


@router.post("/{username}/block")
async def block_user(username: str):
    """Заблокировать пользователя."""
    raise HTTPException(501, "not implemented")


@router.post("/{username}/unblock")
async def unblock_user(username: str):
    """Разблокировать пользователя."""
    raise HTTPException(501, "not implemented")


@router.delete("/{username}")
async def delete_user(username: str):
    """Удалить пользователя."""
    raise HTTPException(501, "not implemented")


@router.patch("/{username}/quota")
async def patch_quota(username: str, patch: UserQuotaPatch):
    """Изменить квоты пользователя."""
    raise HTTPException(501, "not implemented")


@router.post("/{username}/can-record")
async def set_can_record(username: str, patch: UserCanRecordPatch):
    """Разрешить/запретить запись."""
    raise HTTPException(501, "not implemented")
