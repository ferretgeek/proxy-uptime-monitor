from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import psutil


def normalized_system_cpu_percent(value: Any) -> float:
    """Return a whole-machine CPU percentage on a strict 0–100 scale."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return round(max(0.0, min(100.0, number)), 1)


def _valid_temperature(value: Any, minimum: float, maximum: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not minimum <= number <= maximum:
        return None
    return round(number, 1)


def _matching_temperatures(
    sensors: Mapping[str, Sequence[Any]],
    groups: set[str],
    label_fragments: tuple[str, ...] = (),
) -> list[float]:
    values: list[float] = []
    for group, entries in sensors.items():
        if group.casefold() not in groups:
            continue
        for entry in entries:
            label = str(getattr(entry, "label", "") or "").casefold()
            if label_fragments and not any(fragment in label for fragment in label_fragments):
                continue
            current = _valid_temperature(
                getattr(entry, "current", None),
                minimum=-20.0,
                maximum=150.0,
            )
            if current is not None:
                values.append(current)
    return values


def read_cpu_temperature(
    sensor_data: Mapping[str, Sequence[Any]] | None = None,
) -> float | None:
    """Read a real CPU package/die sensor without guessing from ACPI ambient data."""

    if sensor_data is None:
        reader = getattr(psutil, "sensors_temperatures", None)
        if reader is None:
            return None
        try:
            sensor_data = reader(fahrenheit=False)
        except (OSError, RuntimeError, NotImplementedError):
            return None
    if not isinstance(sensor_data, Mapping):
        return None

    preferences = (
        ({"coretemp"}, ("package",)),
        ({"k10temp", "zenpower"}, ("tdie",)),
        ({"k10temp", "zenpower"}, ("tctl",)),
        ({"cpu_thermal", "soc_thermal", "x86_pkg_temp"}, ()),
        ({"coretemp"}, ()),
    )
    for groups, labels in preferences:
        values = _matching_temperatures(sensor_data, groups, labels)
        if values:
            # Multi-socket hosts are represented by their hottest package.
            return max(values)
    return None


def read_disk_temperature(
    cache_path: Path,
    *,
    max_age_seconds: int = 600,
    now_epoch: float | None = None,
) -> float | None:
    """Read the root-owned SMART cache only while it is fresh and plausible."""

    try:
        metadata = cache_path.stat()
        now = time.time() if now_epoch is None else now_epoch
        age = max(0.0, now - metadata.st_mtime)
        if age > max_age_seconds:
            return None
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _valid_temperature(
        payload.get("disk_temperature_c"),
        minimum=0.0,
        maximum=100.0,
    )


def read_hardware_temperatures(runtime_dir: Path) -> tuple[float | None, float | None]:
    return (
        read_cpu_temperature(),
        read_disk_temperature(runtime_dir / "hardware.json"),
    )
