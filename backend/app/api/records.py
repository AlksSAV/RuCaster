"""Records API: запись статики."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db.schemas import RecordFullResponse, RecordStartResponse

router = APIRouter()


@router.post("/{mountpoint}", response_model=RecordStartResponse)
async def start_record(mountpoint: str, request):
    """Начать запись RTCM-потока."""
    # TODO: реализовать запись в файл
    raise HTTPException(501, "not implemented")


@router.get("", response_model=RecordFullResponse)
async def get_records():
    """Список активных записей и диск."""
    return RecordFullResponse()


@router.delete("/{pid}")
async def stop_record(pid: str):
    """Остановить запись."""
    # TODO: реализовать
    raise HTTPException(501, "not implemented")


@router.get("/{mp}")
async def get_mountpoint_records(mp: str):
    """Файлы записей для mountpoint."""
    # TODO: реализовать
    raise HTTPException(501, "not implemented")


@router.get("/{mp}/{fname}")
async def download_record(mp: str, fname: str):
    """Скачать файл записи."""
    # TODO: реализовать
    raise HTTPException(501, "not implemented")


@router.get("/{mp}/day/{date}")
async def get_day_archive(mp: str, date: str):
    """Zip-архив за день."""
    # TODO: реализовать
    raise HTTPException(501, "not implemented")
