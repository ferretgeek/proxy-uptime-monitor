from __future__ import annotations

import asyncio
import importlib.util
import io
import tarfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.database import _safe_csv_cell
from app.request_limits import RequestBodyLimitMiddleware
from app.subscriptions import SubscriptionError, _bounded_plain_copy

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str) -> ModuleType:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_environment_file_is_data_not_shell(tmp_path: Path) -> None:
    helper = _load_script("safe_environment")
    marker = tmp_path / "executed"
    environment = tmp_path / "env"
    environment.write_text(
        f"AIRPORT_BIND_HOST=127.0.0.1\n"
        f"AIRPORT_PORT=$(touch {marker})\n",
        encoding="utf-8",
    )
    values = helper.parse_environment_file(environment)
    assert values["AIRPORT_PORT"].startswith("$(touch")
    assert not marker.exists()
    with pytest.raises(ValueError, match="整数"):
        helper.health_url(values)


def test_restore_archive_rejects_links_and_unknown_entries(tmp_path: Path) -> None:
    helper = _load_script("restore_archive")
    archive_path = tmp_path / "bad.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        database = tarfile.TarInfo("monitor.db")
        database.size = 2
        archive.addfile(database, io.BytesIO(b"db"))
        environment = tarfile.TarInfo("env")
        environment.size = 3
        archive.addfile(environment, io.BytesIO(b"x=1"))
        link = tarfile.TarInfo("manifest")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/shadow"
        archive.addfile(link)
    with pytest.raises(ValueError, match="普通文件"):
        helper.extract_restore_archive(archive_path, tmp_path / "out")


def test_maintenance_scripts_never_source_environment_file() -> None:
    for name in ("backup.sh", "install.sh", "restore.sh", "update.sh"):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert ". /etc/airport-monitor/env" not in text
        assert "source /etc/airport-monitor/env" not in text


def test_yaml_alias_expansion_budget_rejects_exponential_graph() -> None:
    value: Any = ["x"] * 10
    for _ in range(6):
        value = [value] * 5
    with pytest.raises(SubscriptionError, match="结构过大"):
        _bounded_plain_copy(value)


@pytest.mark.parametrize("value", ["=1+1", " +cmd", "\t@SUM(A1:A2)", "-2+3"])
def test_csv_formula_prefixes_are_neutralized(value: str) -> None:
    assert _safe_csv_cell(value).startswith("'")


def test_request_body_limit_rejects_declared_login_body_without_reading() -> None:
    received = False
    sent: list[dict[str, Any]] = []

    async def app(_scope: dict[str, Any], _receive: Any, _send: Any) -> None:
        raise AssertionError("oversized request must not reach the application")

    async def receive() -> dict[str, Any]:
        nonlocal received
        received = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/login",
        "headers": [(b"content-length", b"4097")],
    }
    asyncio.run(RequestBodyLimitMiddleware(app)(scope, receive, send))
    assert sent[0]["status"] == 413
    assert received is False
