"""Records API: запись статики (T-007)."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.models import SourceModel, UserModel
from app.db.schemas import (
    DiskInfo,
    RecordFullResponse,
    RecordResponse,
    RecordStartRequest,
    RecordStartResponse,
)
from app.db.session import get_session
from app.services.recorder import FILE_RE, RecordManager

router = APIRouter()


def _manager(request: Request) -> RecordManager:
    manager = getattr(request.app.state.ctx, "record_manager", None)
    if manager is None:
        raise HTTPException(503, "менеджер записей не инициализирован")
    return manager


async def _source_or_404(mountpoint: str, session: AsyncSession) -> SourceModel:
    stmt = select(SourceModel).where(SourceModel.mountpoint == mountpoint)
    source = (await session.execute(stmt)).scalar_one_or_none()
    if not source:
        raise HTTPException(404, "источник не найден")
    return source


def _ensure_access(source: SourceModel, user: UserModel) -> None:
    """Записи источника доступны его владельцу и админу."""
    if source.owner_id != user.id and user.role != "admin":
        raise HTTPException(403, "нет доступа к записям чужого источника")


def _safe_name(fname: str) -> str:
    """Имя файла записи без выхода за пределы каталога mountpoint."""
    if not FILE_RE.match(fname):
        raise HTTPException(400, "некорректное имя файла")
    return fname


@router.post("/{mountpoint}", response_model=RecordStartResponse)
async def start_record(
    mountpoint: str,
    request: Request,
    req: RecordStartRequest | None = None,
    session: AsyncSession = Depends(get_session),
    user: UserModel = Depends(get_current_user),
):
    """Начать запись RTCM-потока источника."""
    source = await _source_or_404(mountpoint, session)
    _ensure_access(source, user)
    if user.role != "admin" and not user.can_record:
        raise HTTPException(403, "запись запрещена для этой учётной записи")

    manager = _manager(request)
    if manager.active_for(mountpoint) is not None:
        raise HTTPException(409, "запись уже идёт")

    duration = req.duration if req else manager.default_duration
    if duration <= 0:
        duration = manager.default_duration
    if duration > manager.max_duration:
        raise HTTPException(
            400, f"длительность больше максимальной ({manager.max_duration} с)"
        )

    rec = manager.start(mountpoint, owner=user.username, duration=duration)
    return RecordStartResponse(**rec.as_dict())


@router.get("", response_model=RecordFullResponse)
async def get_records(request: Request, user: UserModel = Depends(get_current_user)):
    """Список активных записей и состояние диска."""
    manager = _manager(request)
    disk = manager.disk_info()
    return RecordFullResponse(
        recording=[RecordResponse(**rec.as_dict()) for rec in manager.records.values()],
        disk=DiskInfo(**disk),
        defaults={
            "duration": manager.default_duration,
            "max_duration": manager.max_duration,
            "retention_days": manager.retention_days,
        },
    )


@router.delete("/{pid}")
async def stop_record(
    pid: str,
    request: Request,
    user: UserModel = Depends(get_current_user),
):
    """Остановить запись."""
    manager = _manager(request)
    rec = manager.records.get(pid)
    if rec is None:
        raise HTTPException(404, "запись не найдена")
    if rec.owner != user.username and user.role != "admin":
        raise HTTPException(403, "нет доступа к чужой записи")
    await manager.stop(pid)
    return {"ok": True}


@router.get("/{mp}")
async def get_mountpoint_records(
    mp: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: UserModel = Depends(get_current_user),
):
    """Файлы записей для mountpoint."""
    source = await _source_or_404(mp, session)
    _ensure_access(source, user)
    return {"mountpoint": mp, "files": _manager(request).files(mp)}


@router.get("/{mp}/day/{date}")
async def get_day_archive(
    mp: str,
    date: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: UserModel = Depends(get_current_user),
):
    """Zip-архив записей за день (date = ГГГГММДД)."""
    try:
        datetime.strptime(date, "%Y%m%d")
    except ValueError:
        raise HTTPException(400, "дата должна быть в формате ГГГГММДД") from None

    source = await _source_or_404(mp, session)
    _ensure_access(source, user)

    files = _manager(request).day_files(mp, date)
    if not files:
        raise HTTPException(404, "за выбранный день записей нет")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as archive:
        for path in files:
            archive.write(path, arcname=path.name)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{mp}_{date}.zip"'},
    )


@router.get("/{mp}/{fname}")
async def download_record(
    mp: str,
    fname: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: UserModel = Depends(get_current_user),
):
    """Скачать файл записи."""
    source = await _source_or_404(mp, session)
    _ensure_access(source, user)

    path = _manager(request).file_path(mp, _safe_name(fname))
    if not path.is_file():
        raise HTTPException(404, "файл не найден")
    return FileResponse(path, media_type="application/octet-stream", filename=fname)
