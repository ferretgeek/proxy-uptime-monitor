#!/usr/bin/env python3
"""在本机数据目录启动航迹，不接触系统级部署目录。"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import secrets
import shutil
import sqlite3
import sys
from pathlib import Path

from cryptography.fernet import Fernet


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _resolve_sing_box(value: str | None) -> Path:
    candidate = Path(value).expanduser() if value else None
    if candidate is None:
        discovered = shutil.which("sing-box")
        candidate = Path(discovered) if discovered else None
    if candidate is None or not candidate.is_file():
        raise SystemExit(
            "未找到 sing-box。请先安装并加入 PATH，或使用 --sing-box 指定可执行文件。"
        )
    return candidate.resolve()


def _load_or_create_runtime_secrets(path: Path) -> dict[str, str]:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data.get("encryption_key") or not data.get("session_pepper"):
            raise SystemExit(f"本地密钥文件不完整：{path}")
        return data
    data = {
        "encryption_key": Fernet.generate_key().decode("ascii"),
        "session_pepper": secrets.token_urlsafe(32),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return data


def _ensure_admin(database_path: Path) -> None:
    from app.database import Database
    from app.security import hash_password

    database = Database(database_path)
    database.migrate()
    with sqlite3.connect(database_path) as connection:
        has_admin = connection.execute("SELECT 1 FROM admins LIMIT 1").fetchone()
    if has_admin:
        return
    print("首次启动需要创建本地管理员。")
    username = input("管理员账号 [admin]：").strip() or "admin"
    password = getpass.getpass("管理员密码（至少 14 个字符）：")
    confirmation = getpass.getpass("再次输入管理员密码：")
    if password != confirmation:
        raise SystemExit("两次输入的密码不一致。")
    if len(password) < 14:
        raise SystemExit("管理员密码至少需要 14 个字符。")
    database.create_admin(username, hash_password(password))
    print("本地管理员已创建。")


def main() -> int:
    parser = argparse.ArgumentParser(description="在本机安全启动航迹")
    parser.add_argument("--bind-host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--sing-box", help="sing-box 可执行文件路径")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=ROOT / ".local-run",
        help="本地数据根目录（默认 .local-run）",
    )
    args = parser.parse_args()
    if args.bind_host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("本地模式只允许绑定 localhost。服务器部署请使用 scripts/install.sh。")
    if not 1 <= args.port <= 65535:
        raise SystemExit("端口必须在 1～65535 之间。")

    data_root = args.data_root.expanduser().resolve()
    runtime_secrets = _load_or_create_runtime_secrets(
        data_root / "runtime-secrets.json"
    )
    environment = {
        "AIRPORT_BIND_HOST": args.bind_host,
        "AIRPORT_PORT": str(args.port),
        "AIRPORT_DATA_DIR": str(data_root / "data"),
        "AIRPORT_RUNTIME_DIR": str(data_root / "run"),
        "AIRPORT_LOG_DIR": str(data_root / "log"),
        "AIRPORT_SING_BOX": str(_resolve_sing_box(args.sing_box)),
        "AIRPORT_ENCRYPTION_KEY": runtime_secrets["encryption_key"],
        "AIRPORT_SESSION_PEPPER": runtime_secrets["session_pepper"],
        "AIRPORT_ALLOWED_HOSTS": "localhost,127.0.0.1,[::1]",
        "AIRPORT_LOG_LEVEL": "INFO",
    }
    os.environ.update(environment)
    _ensure_admin(data_root / "data" / "monitor.db")

    from app.main import run

    print(f"航迹本地服务已准备：http://{args.bind_host}:{args.port}")
    print(f"本地数据目录：{data_root}")
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
