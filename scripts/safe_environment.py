#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import os
import re
from pathlib import Path

KEY_PATTERN = re.compile(r"AIRPORT_[A-Z0-9_]{1,80}")
MAX_ENV_BYTES = 64 * 1024


def parse_environment_file(path: Path) -> dict[str, str]:
    if path.stat().st_size > MAX_ENV_BYTES:
        raise ValueError("环境文件超过 64 KiB 安全上限")
    values: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"环境文件第 {number} 行缺少等号")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError(f"环境文件第 {number} 行键名无效")
        if "\x00" in value or len(value.encode("utf-8")) > 8192:
            raise ValueError(f"环境文件第 {number} 行值无效")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def health_url(values: dict[str, str]) -> str:
    host = values.get("AIRPORT_BIND_HOST", "127.0.0.1").strip()
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("AIRPORT_BIND_HOST 必须是 IP 地址") from exc
    if address.is_unspecified:
        address = ipaddress.ip_address("::1" if address.version == 6 else "127.0.0.1")
    try:
        port = int(values.get("AIRPORT_PORT", "18080"))
    except ValueError as exc:
        raise ValueError("AIRPORT_PORT 必须是整数") from exc
    if not 1 <= port <= 65535:
        raise ValueError("AIRPORT_PORT 超出有效范围")
    rendered = f"[{address}]" if address.version == 6 else str(address)
    return f"http://{rendered}:{port}/api/health"


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    health_parser = subparsers.add_parser("health-url")
    health_parser.add_argument("environment", type=Path)
    exec_parser = subparsers.add_parser("exec")
    exec_parser.add_argument("environment", type=Path)
    exec_parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    values = parse_environment_file(args.environment)
    if args.action == "health-url":
        print(health_url(values))
        return 0
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        parser.error("exec 需要命令")
    environment = os.environ.copy()
    environment.update(values)
    os.execvpe(command[0], command, environment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
