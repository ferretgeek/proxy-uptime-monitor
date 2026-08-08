from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.telemetry import (
    normalized_system_cpu_percent,
    read_cpu_temperature,
    read_disk_temperature,
)

ROOT = Path(__file__).resolve().parents[1]


def _temperature(label: str, current: float) -> SimpleNamespace:
    return SimpleNamespace(label=label, current=current)


def test_system_cpu_is_normalized_to_whole_machine_scale() -> None:
    assert normalized_system_cpu_percent(8.04) == 8.0
    assert normalized_system_cpu_percent(125.0) == 100.0
    assert normalized_system_cpu_percent(-2.0) == 0.0
    assert normalized_system_cpu_percent("unknown") == 0.0


def test_cpu_temperature_prefers_package_sensor() -> None:
    sensors = {
        "acpitz": [_temperature("", 27.8)],
        "coretemp": [
            _temperature("Package id 0", 49.0),
            _temperature("Core 0", 42.0),
            _temperature("Core 1", 53.0),
        ],
    }
    assert read_cpu_temperature(sensors) == 49.0


def test_cpu_temperature_does_not_guess_from_ambient_sensor() -> None:
    assert read_cpu_temperature({"acpitz": [_temperature("", 31.0)]}) is None


def test_disk_temperature_cache_must_be_fresh_and_plausible(tmp_path: Path) -> None:
    path = tmp_path / "hardware.json"
    path.write_text(json.dumps({"disk_temperature_c": 48.0}), encoding="utf-8")
    modified = path.stat().st_mtime
    assert read_disk_temperature(path, now_epoch=modified + 60) == 48.0
    assert read_disk_temperature(path, now_epoch=modified + 601) is None
    path.write_text(json.dumps({"disk_temperature_c": 180}), encoding="utf-8")
    assert read_disk_temperature(path, now_epoch=path.stat().st_mtime) is None


def test_hardware_probe_does_not_hide_unexpected_failures() -> None:
    probe = (ROOT / "deploy" / "hardware_probe.py").read_text(encoding="utf-8")
    assert "except Exception" not in probe
    assert "cache write failed" in probe
