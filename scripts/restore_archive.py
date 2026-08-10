#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import stat
import tarfile
from pathlib import Path

LIMITS = {
    "monitor.db": 15 * 1024**3,
    "env": 64 * 1024,
    "manifest": 64 * 1024,
}
REQUIRED = {"monitor.db", "env"}


def extract_restore_archive(archive_path: Path, destination: Path) -> None:
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    seen: set[str] = set()
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            if member.name not in LIMITS or member.name in seen:
                raise ValueError("备份包包含未知或重复条目")
            if not member.isfile() or member.issym() or member.islnk():
                raise ValueError("备份包条目必须是普通文件")
            if member.size < 0 or member.size > LIMITS[member.name]:
                raise ValueError("备份包条目超过安全上限")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("无法读取备份包条目")
            target = destination / member.name
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(target, flags, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            if not stat.S_ISREG(os.lstat(target).st_mode):
                raise ValueError("恢复目标不是普通文件")
            seen.add(member.name)
    if not REQUIRED.issubset(seen):
        raise ValueError("备份包缺少数据库或加密配置")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    extract_restore_archive(args.archive, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
