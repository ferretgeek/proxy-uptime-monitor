from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少必需环境变量：{name}")
    return value


@dataclass(frozen=True)
class AppConfig:
    bind_host: str
    port: int
    data_dir: Path
    runtime_dir: Path
    log_dir: Path
    sing_box_path: Path
    encryption_key: str
    session_pepper: str
    allowed_hosts: tuple[str, ...]
    log_level: str
    hardware_cpu_label: str = ""
    hardware_memory_label: str = ""
    hardware_disk_label: str = ""

    @property
    def database_path(self) -> Path:
        return self.data_dir / "monitor.db"

    @property
    def static_dir(self) -> Path:
        return Path(__file__).resolve().parent / "static"

    @property
    def hardware_profile(self) -> dict[str, str]:
        return {
            "cpu": self.hardware_cpu_label,
            "memory": self.hardware_memory_label,
            "disk": self.hardware_disk_label,
        }

    @classmethod
    def from_env(cls) -> "AppConfig":
        bind_host = os.environ.get("AIRPORT_BIND_HOST", "127.0.0.1").strip()
        port = int(os.environ.get("AIRPORT_PORT", "18080"))
        if not 1 <= port <= 65535:
            raise RuntimeError("AIRPORT_PORT 必须在 1～65535 之间")
        allowed = tuple(
            item.strip()
            for item in os.environ.get(
                "AIRPORT_ALLOWED_HOSTS", f"{bind_host},localhost,127.0.0.1"
            ).split(",")
            if item.strip()
        )
        return cls(
            bind_host=bind_host,
            port=port,
            data_dir=Path(
                os.environ.get("AIRPORT_DATA_DIR", "/var/lib/airport-monitor")
            ),
            runtime_dir=Path(
                os.environ.get("AIRPORT_RUNTIME_DIR", "/run/airport-monitor")
            ),
            log_dir=Path(
                os.environ.get("AIRPORT_LOG_DIR", "/var/log/airport-monitor")
            ),
            sing_box_path=Path(
                os.environ.get(
                    "AIRPORT_SING_BOX", "/opt/airport-monitor/bin/sing-box"
                )
            ),
            encryption_key=_required("AIRPORT_ENCRYPTION_KEY"),
            session_pepper=_required("AIRPORT_SESSION_PEPPER"),
            allowed_hosts=allowed,
            log_level=os.environ.get("AIRPORT_LOG_LEVEL", "INFO").upper(),
            hardware_cpu_label=os.environ.get(
                "AIRPORT_HARDWARE_CPU", ""
            ).strip()[:120],
            hardware_memory_label=os.environ.get(
                "AIRPORT_HARDWARE_MEMORY", ""
            ).strip()[:120],
            hardware_disk_label=os.environ.get(
                "AIRPORT_HARDWARE_DISK", ""
            ).strip()[:120],
        )

    def ensure_runtime_directories(self) -> None:
        for path in (self.data_dir, self.runtime_dir, self.log_dir):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
