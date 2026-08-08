from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run-local.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("airport_monitor_local_runner", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_secrets_are_generated_once_in_private_local_file(tmp_path: Path) -> None:
    runner = _load_runner()
    secret_path = tmp_path / "runtime-secrets.json"
    first = runner._load_or_create_runtime_secrets(secret_path)
    second = runner._load_or_create_runtime_secrets(secret_path)
    assert first == second
    assert len(first["encryption_key"]) >= 40
    assert len(first["session_pepper"]) >= 32
    assert secret_path.exists()


def test_local_runner_rejects_non_loopback_bind_before_starting(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--bind-host",
            "0.0.0.0",
            "--sing-box",
            sys.executable,
            "--data-root",
            str(tmp_path / "local-data"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "只允许绑定 localhost" in (result.stdout + result.stderr)
    assert not (tmp_path / "local-data").exists()


def test_local_runner_help_is_available() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--sing-box" in result.stdout
    assert "--data-root" in result.stdout
