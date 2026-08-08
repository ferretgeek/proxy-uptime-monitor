from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .config import AppConfig


GIB = 1024 * 1024 * 1024
LOG_SOFT_BYTES = 8 * GIB
LOG_HARD_BYTES = 10 * GIB
TOTAL_SOFT_BYTES = 12 * GIB
TOTAL_HARD_BYTES = 15 * GIB


def _path_size(path: Path) -> int:
    try:
        if path.is_symlink():
            return 0
        if path.is_file():
            return path.stat().st_size
        if not path.is_dir():
            return 0
    except OSError:
        return 0
    total = 0
    try:
        for root, directories, files in os.walk(path, followlinks=False):
            directories[:] = [
                name
                for name in directories
                if not (Path(root) / name).is_symlink()
            ]
            for name in files:
                item = Path(root) / name
                try:
                    if not item.is_symlink():
                        total += item.stat().st_size
                except OSError:
                    continue
    except OSError:
        return total
    return total


def _sum_files(paths: Iterable[Path]) -> int:
    return sum(_path_size(path) for path in paths)


@dataclass(frozen=True)
class StorageSnapshot:
    sampled_at: str
    database_bytes: int
    data_bytes: int
    log_bytes: int
    runtime_bytes: int
    install_bytes: int
    backup_bytes: int
    config_bytes: int
    total_bytes: int
    log_soft_bytes: int = LOG_SOFT_BYTES
    log_hard_bytes: int = LOG_HARD_BYTES
    total_soft_bytes: int = TOTAL_SOFT_BYTES
    total_hard_bytes: int = TOTAL_HARD_BYTES
    pressure: str = "normal"
    source: str = "application"

    def as_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in self.__dict__.items()
        }


class StorageManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self.status_path = config.data_dir / "storage-status.json"
        self.install_root = Path("/opt/airport-monitor")
        self.backup_root = Path("/var/backups/airport-monitor")
        self.config_root = Path("/etc/airport-monitor")

    def _root_snapshot(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.status_path.read_text(encoding="utf-8"))
            sampled = datetime.fromisoformat(
                str(payload.get("sampled_at", "")).replace("Z", "+00:00")
            )
            if sampled.tzinfo is None:
                sampled = sampled.replace(tzinfo=UTC)
            if (datetime.now(UTC) - sampled).total_seconds() > 4 * 3600:
                return None
            if not isinstance(payload.get("total_bytes"), int):
                return None
            return payload
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def snapshot(self) -> StorageSnapshot:
        database_bytes = _sum_files(
            (
                self.config.database_path,
                Path(f"{self.config.database_path}-wal"),
                Path(f"{self.config.database_path}-shm"),
            )
        )
        data_bytes = _path_size(self.config.data_dir)
        log_bytes = _path_size(self.config.log_dir)
        runtime_bytes = _path_size(self.config.runtime_dir)
        root = self._root_snapshot()
        install_bytes = (
            int(root.get("install_bytes", 0))
            if root
            else _path_size(self.install_root)
        )
        backup_bytes = (
            int(root.get("backup_bytes", 0))
            if root
            else _path_size(self.backup_root)
        )
        config_bytes = (
            int(root.get("config_bytes", 0))
            if root
            else _path_size(self.config_root)
        )
        total = (
            data_bytes
            + log_bytes
            + runtime_bytes
            + install_bytes
            + backup_bytes
            + config_bytes
        )
        if log_bytes >= LOG_HARD_BYTES or total >= TOTAL_HARD_BYTES:
            pressure = "critical"
        elif log_bytes >= LOG_SOFT_BYTES or total >= TOTAL_SOFT_BYTES:
            pressure = "warning"
        else:
            pressure = "normal"
        return StorageSnapshot(
            sampled_at=datetime.now(UTC).isoformat(timespec="seconds"),
            database_bytes=database_bytes,
            data_bytes=data_bytes,
            log_bytes=log_bytes,
            runtime_bytes=runtime_bytes,
            install_bytes=install_bytes,
            backup_bytes=backup_bytes,
            config_bytes=config_bytes,
            total_bytes=total,
            pressure=pressure,
            source="root_guard" if root else "application",
        )

    def enforce_log_cap(self) -> dict[str, int | bool]:
        files = [
            path
            for path in self.config.log_dir.glob("**/*")
            if path.is_file() and path.name != "app.log"
        ]
        total = _path_size(self.config.log_dir)
        removed = 0
        removed_bytes = 0
        if total > LOG_SOFT_BYTES:
            for path in sorted(files, key=lambda item: item.stat().st_mtime):
                try:
                    size = path.stat().st_size
                    path.unlink()
                    total -= size
                    removed += 1
                    removed_bytes += size
                    if total <= LOG_SOFT_BYTES:
                        break
                except OSError:
                    continue
        truncated = False
        if total > LOG_HARD_BYTES:
            active = self.config.log_dir / "app.log"
            try:
                size = active.stat().st_size
                with active.open("r+b") as handle:
                    handle.truncate(0)
                total -= size
                removed_bytes += size
                truncated = True
            except OSError:
                pass
        return {
            "removed_files": removed,
            "removed_bytes": removed_bytes,
            "active_log_truncated": truncated,
            "remaining_bytes": max(0, total),
        }
