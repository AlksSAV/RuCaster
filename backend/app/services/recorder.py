"""Запись RTCM-потока источника в файлы (T-007).

Схема хранения: `<records_dir>/<mountpoint>/<ГГГГММДД>_<ЧЧММ>.rtcm`.
Файл ротируется при смене календарных суток (UTC), ретенция — по дате в имени.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import shutil
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiofiles

if TYPE_CHECKING:
    from app.ntrip.hub import NtripHub

log = logging.getLogger("rucaster.records")

# Имя файла записи: 20261119_1340.rtcm
FILE_RE = re.compile(r"^\d{8}_\d{4}\.rtcm$")
_UNSAFE_MP = re.compile(r"[^A-Za-z0-9._-]")

# Сколько чанков держим в очереди писателя (при переполнении чанк теряется)
_QUEUE_SIZE = 2048
# Интервал проверки ретенции
_RETENTION_INTERVAL_S = 3600.0


def safe_mountpoint(mountpoint: str) -> str:
    """Имя каталога для mountpoint: без символов, выходящих за пределы records_dir."""
    return _UNSAFE_MP.sub("_", mountpoint)


class Recording:
    """Активная запись: очередь чанков и задача-писатель."""

    def __init__(
        self,
        manager: RecordManager,
        mountpoint: str,
        owner: str,
        duration: int,
    ) -> None:
        self.id = str(uuid.uuid4())
        self.manager = manager
        self.mountpoint = mountpoint
        self.owner = owner
        self.duration = duration
        self.started_at = datetime.now(UTC)
        self.bytes_total = 0
        self.dropped_chunks = 0
        self.alive = True
        self.file_path: Path | None = None
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._fh: Any = None
        self._file_day: date | None = None
        self._task: asyncio.Task | None = None

    # ---------- sink (вызывается из потока источника) ----------

    def feed(self, data: bytes) -> None:
        """Принять чанк потока. Медленный диск не должен тормозить NTRIP."""
        if not self.alive:
            return
        try:
            self.queue.put_nowait(data)
        except asyncio.QueueFull:
            self.dropped_chunks += 1

    # ---------- писатель ----------

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.duration if self.duration else None
        try:
            while True:
                timeout = None
                if deadline is not None:
                    timeout = deadline - loop.time()
                    if timeout <= 0:
                        break
                try:
                    chunk = await asyncio.wait_for(self.queue.get(), timeout)
                except TimeoutError:
                    break
                await self._write(chunk)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Record %s (%s) failed", self.id, self.mountpoint)
        finally:
            await self._finalize()

    async def _finalize(self) -> None:
        """Дописать очередь, закрыть файл, снять подписку. Идемпотентно."""
        if not self.alive and self._fh is None:
            return
        self.alive = False
        while not self.queue.empty():
            await self._write(self.queue.get_nowait())
        await self._close_file()
        self.manager._unregister(self)
        log.info(
            "Record %s (%s) stopped: %d bytes, dropped %d",
            self.id,
            self.mountpoint,
            self.bytes_total,
            self.dropped_chunks,
        )

    async def _write(self, chunk: bytes) -> None:
        now = datetime.now(UTC)
        if self._fh is None or self._file_day != now.date():
            await self._open_file(now)
        assert self._fh is not None
        await self._fh.write(chunk)
        await self._fh.flush()
        self.bytes_total += len(chunk)

    async def _open_file(self, now: datetime) -> None:
        """Открыть файл текущих суток (ротация по дате)."""
        await self._close_file()
        directory = self.manager.root / safe_mountpoint(self.mountpoint)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{now:%Y%m%d}_{now:%H%M}.rtcm"
        self._fh = await aiofiles.open(path, "ab")
        self.file_path = path
        self._file_day = now.date()

    async def _close_file(self) -> None:
        if self._fh is None:
            return
        try:
            await self._fh.flush()
        finally:
            await self._fh.close()
            self._fh = None

    async def stop(self) -> None:
        """Остановить запись и дождаться закрытия файла."""
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._finalize()

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "mountpoint": self.mountpoint,
            "owner": self.owner,
            "started_at": self.started_at,
            "duration": self.duration,
            "alive": self.alive,
        }


class RecordManager:
    """Активные записи, статистика диска, ретенция."""

    def __init__(
        self,
        hub: NtripHub,
        root: str | Path,
        retention_days: int,
        default_duration: int,
        max_duration: int,
    ) -> None:
        self.hub = hub
        self.root = Path(root)
        self.retention_days = retention_days
        self.default_duration = default_duration
        self.max_duration = max_duration
        self.records: dict[str, Recording] = {}
        self._retention_task: asyncio.Task | None = None

    # ---------- управление ----------

    def active_for(self, mountpoint: str) -> Recording | None:
        for rec in self.records.values():
            if rec.mountpoint == mountpoint:
                return rec
        return None

    def start(self, mountpoint: str, owner: str, duration: int) -> Recording:
        """Начать запись; подписаться на поток источника в hub."""
        rec = Recording(self, mountpoint, owner, duration)
        self.records[rec.id] = rec
        self.hub.add_sink(mountpoint, rec.feed)
        rec._task = asyncio.create_task(rec.run())
        log.info("Record %s started: %s, %s s", rec.id, mountpoint, duration)
        return rec

    async def stop(self, record_id: str) -> bool:
        rec = self.records.get(record_id)
        if rec is None:
            return False
        await rec.stop()
        return True

    def _unregister(self, rec: Recording) -> None:
        self.hub.remove_sink(rec.mountpoint, rec.feed)
        self.records.pop(rec.id, None)

    async def shutdown(self) -> None:
        if self._retention_task is not None:
            self._retention_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._retention_task
            self._retention_task = None
        for rec in list(self.records.values()):
            await rec.stop()

    # ---------- файлы ----------

    def _dir(self, mountpoint: str) -> Path:
        return self.root / safe_mountpoint(mountpoint)

    def file_path(self, mountpoint: str, name: str) -> Path:
        """Путь к файлу записи (имя должно пройти проверку FILE_RE)."""
        return self._dir(mountpoint) / name

    def files(self, mountpoint: str) -> list[dict]:
        directory = self._dir(mountpoint)
        if not directory.is_dir():
            return []
        items = [
            {"name": p.name, "bytes": p.stat().st_size}
            for p in directory.iterdir()
            if p.is_file() and FILE_RE.match(p.name)
        ]
        return sorted(items, key=lambda f: f["name"], reverse=True)

    def day_files(self, mountpoint: str, day: str) -> list[Path]:
        directory = self._dir(mountpoint)
        if not directory.is_dir():
            return []
        return sorted(p for p in directory.iterdir() if p.is_file() and p.name.startswith(day))

    def disk_info(self) -> dict:
        mountpoints: list[dict] = []
        total = 0
        if self.root.is_dir():
            for directory in sorted(self.root.iterdir()):
                if not directory.is_dir():
                    continue
                files = [p for p in directory.iterdir() if p.is_file() and FILE_RE.match(p.name)]
                if not files:
                    continue
                size = sum(p.stat().st_size for p in files)
                mountpoints.append(
                    {"mountpoint": directory.name, "bytes": size, "files": len(files)}
                )
                total += size
        free = shutil.disk_usage(self.root).free if self.root.is_dir() else 0
        return {"mountpoints": mountpoints, "total_bytes": total, "free_bytes": free}

    # ---------- ретенция ----------

    def purge_expired(self, today: date | None = None) -> int:
        """Удалить файлы старше retention_days (дата берётся из имени файла)."""
        if not self.root.is_dir():
            return 0
        cutoff = (today or datetime.now(UTC).date()) - timedelta(days=self.retention_days)
        removed = 0
        for directory in list(self.root.iterdir()):
            if not directory.is_dir():
                continue
            for path in list(directory.iterdir()):
                if not path.is_file() or not FILE_RE.match(path.name):
                    continue
                try:
                    file_day = datetime.strptime(path.name[:8], "%Y%m%d").date()
                except ValueError:
                    continue
                if file_day < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            if not any(directory.iterdir()):
                with contextlib.suppress(OSError):
                    directory.rmdir()
        return removed

    def start_retention(self) -> None:
        self._retention_task = asyncio.create_task(self._retention_loop())

    async def _retention_loop(self) -> None:
        while True:
            try:
                removed = self.purge_expired()
                if removed:
                    log.info("Retention removed %d file(s)", removed)
            except Exception:  # noqa: BLE001 — цикл не должен умирать
                log.exception("Retention purge failed")
            await asyncio.sleep(_RETENTION_INTERVAL_S)
