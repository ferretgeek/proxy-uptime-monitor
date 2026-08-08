"""仅供本机浏览器视觉验收，部署包会排除此文件。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet


ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = ROOT / ".local-test"
sys.path.insert(0, str(ROOT))
os.environ.update(
    {
        "AIRPORT_BIND_HOST": "127.0.0.1",
        "AIRPORT_PORT": "18089",
        "AIRPORT_DATA_DIR": str(TEST_ROOT / "data"),
        "AIRPORT_RUNTIME_DIR": str(TEST_ROOT / "run"),
        "AIRPORT_LOG_DIR": str(TEST_ROOT / "log"),
        "AIRPORT_SING_BOX": sys.executable,
        "AIRPORT_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "AIRPORT_SESSION_PEPPER": "local-browser-test-pepper-not-production",
        "AIRPORT_ALLOWED_HOSTS": "127.0.0.1,localhost",
        "AIRPORT_LOG_LEVEL": "INFO",
        "AIRPORT_HARDWARE_CPU": "Intel Core i7-8700T ES",
        "AIRPORT_HARDWARE_MEMORY": "DDR4-2666 8 GB × 2",
        "AIRPORT_HARDWARE_DISK": "英睿达 MX500 500 GB",
    }
)

from app.database import Database  # noqa: E402
from app.security import hash_password  # noqa: E402


database = Database(TEST_ROOT / "data" / "monitor.db")
database.migrate()
database.create_admin("admin", hash_password("LocalVisualTest-2026-Only"))

from app.main import run  # noqa: E402


if __name__ == "__main__":
    run()
