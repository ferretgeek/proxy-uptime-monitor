#!/usr/bin/env python3
"""Write a small, unprivileged-readable cache of real SMART temperatures."""

from __future__ import annotations

import grp
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


CACHE_PATH = Path("/run/airport-monitor/hardware.json")
DEVICE_PATTERN = re.compile(r"^/dev/[A-Za-z0-9._/+:-]+$")
NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


def _valid_temperature(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not 0.0 <= number <= 100.0:
        return None
    return round(number, 1)


def _number_from(value: Any) -> float | None:
    direct = _valid_temperature(value)
    if direct is not None:
        return direct
    match = NUMBER_PATTERN.search(str(value or ""))
    return _valid_temperature(match.group(0)) if match else None


def _smartctl_path() -> str | None:
    return (
        shutil.which("smartctl")
        or next(
            (
                candidate
                for candidate in ("/usr/sbin/smartctl", "/usr/bin/smartctl")
                if Path(candidate).is_file()
            ),
            None,
        )
    )


def _run_json(arguments: list[str]) -> dict[str, Any] | None:
    try:
        result = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _scan_devices(smartctl: str) -> list[tuple[str, str | None]]:
    payload = _run_json([smartctl, "--scan-open", "--json=o"])
    devices: list[tuple[str, str | None]] = []
    for item in (payload or {}).get("devices", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", ""))
        device_type = str(item.get("type", "")).strip() or None
        if DEVICE_PATTERN.fullmatch(name):
            devices.append((name, device_type))
    return devices[:16]


def _extract_temperature(payload: dict[str, Any]) -> float | None:
    direct_paths = (
        ("temperature", "current"),
        ("nvme_smart_health_information_log", "temperature"),
        ("scsi_temperature", "current"),
    )
    for first, second in direct_paths:
        parent = payload.get(first)
        if isinstance(parent, dict):
            value = _number_from(parent.get(second))
            if value is not None:
                return value

    attributes = payload.get("ata_smart_attributes", {})
    table = attributes.get("table", []) if isinstance(attributes, dict) else []
    for preferred_id in (194, 190):
        for item in table:
            if not isinstance(item, dict) or item.get("id") != preferred_id:
                continue
            raw = item.get("raw", {})
            if not isinstance(raw, dict):
                continue
            value = _number_from(raw.get("value"))
            if value is None:
                value = _number_from(raw.get("string"))
            if value is not None:
                return value
    return None


def _read_disk_temperature() -> tuple[float | None, int]:
    smartctl = _smartctl_path()
    if not smartctl:
        return None, 0
    temperatures: list[float] = []
    devices = _scan_devices(smartctl)
    for name, device_type in devices:
        command = [smartctl, "-A", "--json=o"]
        if device_type:
            command.extend(("-d", device_type))
        command.append(name)
        payload = _run_json(command)
        if payload:
            temperature = _extract_temperature(payload)
            if temperature is not None:
                temperatures.append(temperature)
    return (max(temperatures) if temperatures else None, len(devices))


def _write_cache(temperature: float | None, device_count: int) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "sampled_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "disk_temperature_c": temperature,
        "device_count": device_count,
        "source": "smartctl",
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".hardware-",
        dir=CACHE_PATH.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o640)
        try:
            os.chown(temporary_name, 0, grp.getgrnam("airportmon").gr_gid)
        except (KeyError, PermissionError):
            pass
        os.replace(temporary_name, CACHE_PATH)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def main() -> int:
    temperature, device_count = _read_disk_temperature()
    try:
        _write_cache(temperature, device_count)
    except OSError as exc:
        print(
            f"hardware temperature cache write failed: {type(exc).__name__}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
