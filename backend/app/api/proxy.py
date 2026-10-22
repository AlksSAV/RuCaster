"""Proxy API: подмена координат."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db.schemas import ProxyCreate, ProxyResponse

router = APIRouter()


@router.get("", response_model=list[ProxyResponse])
async def list_proxies():
    """Список активных подмен."""
    return []


@router.post("", response_model=ProxyResponse, status_code=201)
async def create_proxy(req: ProxyCreate):
    """Создать подмену координат."""
    # TODO: реализовать логику подмены
    raise HTTPException(501, "not implemented")


@router.delete("/{pid}")
async def delete_proxy(pid: str):
    """Удалить подмену."""
    # TODO: реализовать
    raise HTTPException(501, "not implemented")


@router.get("/{pid}/check-upstream")
async def check_upstream(pid: str):
    """Проверить апстрим подмены."""
    # TODO: реализовать
    raise HTTPException(501, "not implemented")
