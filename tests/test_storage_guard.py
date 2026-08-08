from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path


def _load_guard():
    path = Path(__file__).resolve().parents[1] / "deploy" / "storage_guard.py"
    spec = importlib.util.spec_from_file_location("storage_guard_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_storage_guard_enforces_hard_log_limit_and_cleans_runtime(
    tmp_path: Path, monkeypatch
):
    guard = _load_guard()
    install = tmp_path / "opt"
    releases = install / "releases"
    data = tmp_path / "data"
    logs = tmp_path / "logs"
    runtime = tmp_path / "runtime"
    backups = tmp_path / "backups"
    config = tmp_path / "config"
    for path in (releases, data, logs, runtime, backups, config):
        path.mkdir(parents=True)

    monkeypatch.setattr(guard, "INSTALL_ROOT", install)
    monkeypatch.setattr(guard, "RELEASE_ROOT", releases)
    monkeypatch.setattr(guard, "DATA_ROOT", data)
    monkeypatch.setattr(guard, "LOG_ROOT", logs)
    monkeypatch.setattr(guard, "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(guard, "BACKUP_ROOT", backups)
    monkeypatch.setattr(guard, "CONFIG_ROOT", config)
    monkeypatch.setattr(guard, "STATUS_PATH", data / "storage-status.json")
    monkeypatch.setattr(
        guard,
        "ALLOWED_DELETE_PARENTS",
        {releases.resolve(), logs.resolve(), runtime.resolve(), backups.resolve()},
    )
    monkeypatch.setattr(guard, "LOG_SOFT", 100)
    monkeypatch.setattr(guard, "LOG_HARD", 150)
    monkeypatch.setattr(guard, "TOTAL_SOFT", 1000)
    monkeypatch.setattr(guard, "TOTAL_HARD", 1200)

    (logs / "app.log").write_bytes(b"a" * 180)
    (logs / "app.log.1.gz").write_bytes(b"b" * 80)
    stale = runtime / "probe-stale"
    stale.mkdir()
    os.utime(stale, (time.time() - 7200, time.time() - 7200))

    assert guard.main() == 0
    assert guard.path_size(logs) <= guard.LOG_HARD
    assert not stale.exists()
    status = json.loads((data / "storage-status.json").read_text(encoding="utf-8"))
    assert status["pressure"] == "normal"
    assert status["freed_bytes"] >= 260
    assert "日志硬上限触发，截断活动日志" in status["actions"]
