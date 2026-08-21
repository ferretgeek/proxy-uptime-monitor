from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from .config import AppConfig
from .database import Database
from .security import SecretBox, hash_password
from .subscriptions import parse_subscription_content


def init_admin(config: AppConfig, username: str) -> int:
    password = sys.stdin.readline().rstrip("\r\n") if not sys.stdin.isatty() else getpass.getpass()
    if len(password) < 14:
        print("管理员密码至少需要 14 个字符", file=sys.stderr)
        return 2
    database = Database(config.database_path)
    database.migrate()
    database.create_admin(username, hash_password(password))
    print("管理员已初始化")
    return 0


def backup(config: AppConfig, destination: str) -> int:
    database = Database(config.database_path)
    database.online_backup(Path(destination))
    print("数据库在线备份已完成")
    return 0


def verify(config: AppConfig) -> int:
    database = Database(config.database_path)
    database.migrate()
    SecretBox(config.encryption_key)
    if not config.sing_box_path.is_file():
        print("sing-box 不存在", file=sys.stderr)
        return 3
    print(
        json.dumps(
            {
                "database": "ok",
                "encryption": "ok",
                "sing_box": "ok",
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="节点体检平台维护工具")
    subparsers = parser.add_subparsers(dest="command", required=True)
    admin_parser = subparsers.add_parser("init-admin")
    admin_parser.add_argument("--username", default="admin")
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("destination")
    subparsers.add_parser("verify")
    args = parser.parse_args()
    config = AppConfig.from_env()
    config.ensure_runtime_directories()
    if args.command == "init-admin":
        return init_admin(config, args.username)
    if args.command == "backup":
        return backup(config, args.destination)
    if args.command == "verify":
        return verify(config)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

