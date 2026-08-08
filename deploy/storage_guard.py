#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path


GIB = 1024 * 1024 * 1024
LOG_SOFT = 8 * GIB
LOG_HARD = 10 * GIB
TOTAL_SOFT = 12 * GIB
TOTAL_HARD = 15 * GIB

INSTALL_ROOT = Path("/opt/airport-monitor")
RELEASE_ROOT = INSTALL_ROOT / "releases"
DATA_ROOT = Path("/var/lib/airport-monitor")
LOG_ROOT = Path("/var/log/airport-monitor")
RUNTIME_ROOT = Path("/run/airport-monitor")
BACKUP_ROOT = Path("/var/backups/airport-monitor")
CONFIG_ROOT = Path("/etc/airport-monitor")
STATUS_PATH = DATA_ROOT / "storage-status.json"

ALLOWED_DELETE_PARENTS = {
    RELEASE_ROOT.resolve(),
    LOG_ROOT.resolve(),
    RUNTIME_ROOT.resolve(),
    BACKUP_ROOT.resolve(),
}
RELEASE_PATTERN = re.compile(r"^\d{8}T\d{6}Z$")
BACKUP_PATTERN = re.compile(r"^airport-monitor-\d{8}T\d{6}Z\.tar\.gz$")


def path_size(path: Path) -> int:
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
    pending = [os.fspath(path)]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def safe_unlink(path: Path) -> int:
    resolved_parent = path.parent.resolve()
    if resolved_parent not in ALLOWED_DELETE_PARENTS:
        raise RuntimeError(f"拒绝删除意外路径：{resolved_parent}")
    size = path_size(path)
    path.unlink(missing_ok=True)
    return size


def safe_rmtree(path: Path) -> int:
    resolved_parent = path.parent.resolve()
    if resolved_parent not in ALLOWED_DELETE_PARENTS:
        raise RuntimeError(f"拒绝删除意外路径：{resolved_parent}")
    size = path_size(path)
    shutil.rmtree(path)
    return size


def snapshot() -> dict[str, int]:
    values = {
        "data_bytes": path_size(DATA_ROOT),
        "log_bytes": path_size(LOG_ROOT),
        "runtime_bytes": path_size(RUNTIME_ROOT),
        "install_bytes": path_size(INSTALL_ROOT),
        "backup_bytes": path_size(BACKUP_ROOT),
        "config_bytes": path_size(CONFIG_ROOT),
    }
    values["total_bytes"] = sum(values.values())
    return values


def clean_stale_runtime(actions: list[str]) -> int:
    freed = 0
    cutoff = time.time() - 3600
    if not RUNTIME_ROOT.is_dir():
        return 0
    for path in RUNTIME_ROOT.iterdir():
        if (
            path.is_dir()
            and not path.is_symlink()
            and path.name.startswith("probe-")
            and path.stat().st_mtime < cutoff
        ):
            freed += safe_rmtree(path)
            actions.append("清理过期检测运行目录")
    return freed


def clean_logs(actions: list[str]) -> int:
    freed = 0
    total = path_size(LOG_ROOT)
    if total <= LOG_SOFT:
        return 0
    candidates = sorted(
        (
            path
            for path in LOG_ROOT.iterdir()
            if path.is_file() and not path.is_symlink() and path.name != "app.log"
        ),
        key=lambda path: path.stat().st_mtime,
    )
    for path in candidates:
        freed += safe_unlink(path)
        total = path_size(LOG_ROOT)
        actions.append("删除最旧归档日志")
        if total <= LOG_SOFT:
            break
    if total > LOG_HARD:
        active = LOG_ROOT / "app.log"
        if active.is_file() and not active.is_symlink():
            active_size = active.stat().st_size
            active.write_bytes(b"")
            freed += active_size
            actions.append("日志硬上限触发，截断活动日志")
    return freed


def clean_backups(actions: list[str], current_total: int) -> int:
    if not BACKUP_ROOT.is_dir():
        return 0
    files = sorted(
        (
            path
            for path in BACKUP_ROOT.iterdir()
            if path.is_file() and BACKUP_PATTERN.fullmatch(path.name)
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    freed = 0
    for path in files[3:]:
        if current_total - freed <= TOTAL_SOFT:
            break
        freed += safe_unlink(path)
        actions.append("容量软限制触发，删除最旧平台备份")
    return freed


def clean_releases(actions: list[str], current_total: int) -> int:
    if not RELEASE_ROOT.is_dir():
        return 0
    current = None
    current_link = INSTALL_ROOT / "current"
    try:
        current = current_link.resolve(strict=True)
    except OSError:
        pass
    releases = sorted(
        (
            path
            for path in RELEASE_ROOT.iterdir()
            if path.is_dir()
            and not path.is_symlink()
            and RELEASE_PATTERN.fullmatch(path.name)
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    protected = set(releases[:2])
    if current:
        protected.add(current)
    freed = 0
    for path in reversed(releases):
        if current_total - freed <= TOTAL_SOFT:
            break
        if path in protected:
            continue
        freed += safe_rmtree(path)
        actions.append("容量软限制触发，删除最旧非活动发布")
    return freed


def write_status(payload: dict[str, object]) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".storage-", dir=DATA_ROOT)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        try:
            shutil.chown(temporary, user="airportmon", group="airportmon")
        except LookupError:
            pass
        os.replace(temporary, STATUS_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    actions: list[str] = []
    before = snapshot()
    freed = clean_stale_runtime(actions)
    freed += clean_logs(actions)
    current = snapshot()
    if current["total_bytes"] > TOTAL_SOFT:
        backup_freed = clean_backups(actions, current["total_bytes"])
        freed += backup_freed
        release_freed = clean_releases(
            actions, current["total_bytes"] - backup_freed
        )
        freed += release_freed
        after = snapshot()
    else:
        after = current
    pressure = (
        "critical"
        if after["log_bytes"] >= LOG_HARD
        or after["total_bytes"] >= TOTAL_HARD
        else "warning"
        if after["log_bytes"] >= LOG_SOFT
        or after["total_bytes"] >= TOTAL_SOFT
        else "normal"
    )
    payload: dict[str, object] = {
        "sampled_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **after,
        "database_bytes": sum(
            path_size(path)
            for path in (
                DATA_ROOT / "monitor.db",
                DATA_ROOT / "monitor.db-wal",
                DATA_ROOT / "monitor.db-shm",
            )
        ),
        "log_soft_bytes": LOG_SOFT,
        "log_hard_bytes": LOG_HARD,
        "total_soft_bytes": TOTAL_SOFT,
        "total_hard_bytes": TOTAL_HARD,
        "pressure": pressure,
        "source": "root_guard",
        "before_total_bytes": before["total_bytes"],
        "freed_bytes": freed,
        "actions": actions,
    }
    write_status(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
