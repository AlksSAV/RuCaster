"""Proxy API: подмена координат (T-008)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.models import ProxyModel, SourceModel, UserModel
from app.db.schemas import ProxyCreate, ProxyResponse
from app.db.session import get_session
from app.services.proxy_service import ProxyService

router = APIRouter()


def _get_proxy_service(request: Request) -> ProxyService:
    """Получить глобальный ProxyService из app.state.ctx."""
    return request.app.state.ctx.proxy_service


def _to_response(p: dict) -> ProxyResponse:
    return ProxyResponse(
        id=p["id"],
        source=p["source_mountpoint"],
        mountpoint=p["target_mountpoint"],
        serve_mountpoint=p.get("serve_mountpoint"),
        mode=p["mode"],
        x=p.get("x"),
        y=p.get("y"),
        z=p.get("z"),
        de=p.get("de"),
        dn=p.get("dn"),
        du=p.get("du"),
        alive=p.get("is_active", False),
        uptime_s=0.0,
        restart_count=0,
        last_error=None,
        error=None,
        owner=p.get("owner_id"),
    )


@router.get("", response_model=list[ProxyResponse])
async def list_proxies(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: UserModel = Depends(get_current_user),
):
    """Список активных подмен текущего пользователя."""
    stmt = select(ProxyModel).where(ProxyModel.owner_id == user.id).order_by(ProxyModel.created_at)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        ProxyResponse(
            id=r.id,
            source=r.source_mountpoint,
            mountpoint=r.target_mountpoint,
            serve_mountpoint=r.target_mountpoint,
            mode=r.mode,
            x=r.x,
            y=r.y,
            z=r.z,
            de=r.de,
            dn=r.dn,
            du=r.du,
            alive=r.is_active,
            uptime_s=0.0,
            restart_count=0,
            last_error=None,
            error=None,
            owner=r.owner_id,
        )
        for r in rows
    ]


@router.post("", response_model=ProxyResponse, status_code=201)
async def create_proxy(
    req: ProxyCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: UserModel = Depends(get_current_user),
):
    """Создать подмену координат."""
    # Проверка квоты
    proxy_count = len(
        (await session.execute(select(ProxyModel).where(ProxyModel.owner_id == user.id)))
        .scalars()
        .all()
    )
    quota = user.quotas_substitutions or 0
    if proxy_count >= quota:
        raise HTTPException(403, f"превышена квота подмен: {proxy_count}/{quota}")

    # Проверка существования source_mountpoint
    source_stmt = select(SourceModel).where(SourceModel.mountpoint == req.mountpoint)
    source = (await session.execute(source_stmt)).scalar_one_or_none()
    if not source:
        raise HTTPException(404, f"источник '{req.mountpoint}' не найден")
    if source.owner_id != user.id and user.role != "admin":
        raise HTTPException(403, "нет доступа к чужому источнику")

    # Проверка уникальности target_mountpoint
    target_mt = (
        req.serve_mountpoint or f"{req.mountpoint}_{'RELAY' if req.mode == 'relay' else 'SHIFTED'}"
    )
    existing = (
        await session.execute(select(ProxyModel).where(ProxyModel.target_mountpoint == target_mt))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"target_mountpoint '{target_mt}' уже занят")

    # Relay-режим: проверяем обязательные поля
    if req.mode == "relay":
        if not req.src_host:
            raise HTTPException(422, "relay: требуется src_host")
        if not req.src_mountpoint:
            raise HTTPException(422, "relay: требуется src_mountpoint")

    proxy_id = str(uuid.uuid4())
    proxy = ProxyModel(
        id=proxy_id,
        owner_id=user.id,
        source_mountpoint=req.mountpoint,
        target_mountpoint=target_mt,
        mode=req.mode,
        x=req.x,
        y=req.y,
        z=req.z,
        de=req.de,
        dn=req.dn,
        du=req.du,
        # relay-параметры
        relay_host=req.src_host,
        relay_port=req.src_port,
        relay_mountpoint=req.src_mountpoint,
        relay_user=req.src_user,
        relay_password=req.src_password,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    session.add(proxy)
    await session.commit()
    await session.refresh(proxy)

    # Активируем в ProxyService
    ps: ProxyService = request.app.state.ctx.proxy_service
    ps.add_proxy(
        proxy_id=proxy_id,
        owner_id=user.id,
        source_mountpoint=req.mountpoint,
        target_mountpoint=target_mt,
        mode=req.mode,
        serve_mountpoint=target_mt,
        x=req.x,
        y=req.y,
        z=req.z,
        de=req.de,
        dn=req.dn,
        du=req.du,
        relay_host=req.src_host,
        relay_port=req.src_port,
        relay_mountpoint=req.src_mountpoint,
        relay_user=req.src_user,
        relay_password=req.src_password,
    )

    # Relay-режим: запускаем relay-задачу
    if req.mode == "relay":
        await ps.activate_relay(
            source_mountpoint=req.mountpoint,
            target_mountpoint=target_mt,
            src_host=req.src_host,
            src_port=req.src_port or 2101,
            src_mountpoint=req.src_mountpoint,
            src_user=req.src_user or "",
            src_password=req.src_password or "",
        )

    return ProxyResponse(
        id=proxy.id,
        source=proxy.source_mountpoint,
        mountpoint=proxy.target_mountpoint,
        serve_mountpoint=proxy.target_mountpoint,
        mode=proxy.mode,
        x=proxy.x,
        y=proxy.y,
        z=proxy.z,
        de=proxy.de,
        dn=proxy.dn,
        du=proxy.du,
        alive=proxy.is_active,
        uptime_s=0.0,
        restart_count=0,
        last_error=None,
        error=None,
        owner=proxy.owner_id,
    )


@router.delete("/{pid}")
async def delete_proxy(
    pid: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: UserModel = Depends(get_current_user),
):
    """Удалить подмену."""
    stmt = select(ProxyModel).where(ProxyModel.id == pid)
    proxy = (await session.execute(stmt)).scalar_one_or_none()
    if not proxy:
        raise HTTPException(404, "подмена не найдена")
    if proxy.owner_id != user.id and user.role != "admin":
        raise HTTPException(403, "нет доступа к чужой подмене")

    await session.delete(proxy)
    await session.commit()

    # Деактивируем в ProxyService
    ps: ProxyService = request.app.state.ctx.proxy_service
    ps.delete_proxy(pid)
    if proxy.mode == "relay":
        await ps.stop_relay(proxy.target_mountpoint)

    return {"ok": True}


@router.get("/{pid}/check-upstream")
async def check_upstream(
    pid: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: UserModel = Depends(get_current_user),
):
    """Проверить апстрим подмены."""
    stmt = select(ProxyModel).where(ProxyModel.id == pid)
    proxy = (await session.execute(stmt)).scalar_one_or_none()
    if not proxy:
        raise HTTPException(404, "подмена не найдена")
    if proxy.owner_id != user.id and user.role != "admin":
        raise HTTPException(403, "нет доступа к чужой подмене")

    ps: ProxyService = request.app.state.ctx.proxy_service
    proxy_dict = ps.get_proxy(pid)
    if not proxy_dict:
        raise HTTPException(404, "подмена не найдена в сервисе")

    result = await ps.check_upstream(proxy_dict)
    return result
