#!/usr/bin/env bash
set -euo pipefail

archive="${1:-}"
confirmation="${2:-}"

if (( EUID != 0 )); then
    printf '请使用 sudo 运行此脚本。\n' >&2
    exit 2
fi
if [[ ! -f "$archive" || "$confirmation" != "--confirm-restore" ]]; then
    printf '%s\n' \
        '用法：sudo bash scripts/restore.sh <备份.tar.gz> --confirm-restore' >&2
    exit 2
fi
temporary_directory="$(mktemp -d /tmp/airport-monitor-restore.XXXXXX)"
cleanup() {
    if [[ "$temporary_directory" == /tmp/airport-monitor-restore.* ]] \
        && [[ -d "$temporary_directory" ]]; then
        rm -rf -- "$temporary_directory"
    fi
}
trap cleanup EXIT
restore_payload="$temporary_directory/payload"
if ! python3 /opt/airport-monitor/current/scripts/restore_archive.py \
    "$archive" "$restore_payload"; then
    printf '备份包结构或大小不符合安全要求。\n' >&2
    exit 3
fi

integrity="$(
    python3 - "$restore_payload/monitor.db" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as connection:
    print(connection.execute("PRAGMA integrity_check").fetchone()[0])
PY
)"
if [[ "$integrity" != "ok" ]]; then
    printf '备份数据库完整性校验失败。\n' >&2
    exit 3
fi

safety_backup="$(bash /opt/airport-monitor/current/scripts/backup.sh)"
systemctl stop airport-monitor.service

install -o root -g airportmon -m 0640 "$restore_payload/env" \
    /etc/airport-monitor/env
rm -f -- \
    /var/lib/airport-monitor/monitor.db-wal \
    /var/lib/airport-monitor/monitor.db-shm
install -o airportmon -g airportmon -m 0600 \
    "$restore_payload/monitor.db" /var/lib/airport-monitor/monitor.db

systemctl start airport-monitor.service
health_url="$(python3 /opt/airport-monitor/current/scripts/safe_environment.py \
    health-url /etc/airport-monitor/env)"
for _attempt in {1..20}; do
    if curl --fail --silent --show-error \
        --connect-timeout 2 --max-time 5 "$health_url" >/dev/null; then
        printf '恢复完成。操作前自动备份：%s\n' "$safety_backup"
        exit 0
    fi
    sleep 1
done

printf '恢复后的服务未通过健康检查。操作前备份：%s\n' \
    "$safety_backup" >&2
exit 4
