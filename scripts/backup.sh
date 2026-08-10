#!/usr/bin/env bash
set -euo pipefail

if (( EUID != 0 )); then
    printf '请使用 sudo 运行此脚本。\n' >&2
    exit 2
fi
if [[ ! -f /etc/airport-monitor/env ]] \
    || [[ ! -x /opt/airport-monitor/current/.venv/bin/python ]]; then
    printf '未检测到完整的平台安装。\n' >&2
    exit 3
fi

backup_root="${1:-/var/backups/airport-monitor}"
install -d -o root -g root -m 0700 "$backup_root"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
work_directory="$(mktemp -d "${backup_root}/.backup-${stamp}.XXXXXX")"
archive_path="${backup_root}/airport-monitor-${stamp}.tar.gz"

cleanup() {
    if [[ "$work_directory" == "${backup_root}/.backup-"* ]] \
        && [[ -d "$work_directory" ]]; then
        rm -rf -- "$work_directory"
    fi
}
trap cleanup EXIT

chmod 0700 "$work_directory"
chown root:airportmon "$work_directory"
chmod 0730 "$work_directory"

PYTHONPATH=/opt/airport-monitor/current python3 \
    /opt/airport-monitor/current/scripts/safe_environment.py exec \
    /etc/airport-monitor/env -- \
    runuser --user airportmon --preserve-environment -- \
    /opt/airport-monitor/current/.venv/bin/python -m app.cli backup \
    "$work_directory/monitor.db" >/dev/null

install -o root -g root -m 0600 /etc/airport-monitor/env \
    "$work_directory/env"
release_target="$(readlink -f /opt/airport-monitor/current)"
printf '%s\n' \
    "created_at=${stamp}" \
    "release=${release_target##*/}" \
    "format=1" > "$work_directory/manifest"
chown root:root "$work_directory/monitor.db" "$work_directory/manifest"
chmod 0600 "$work_directory/monitor.db" "$work_directory/manifest"

tar -czf "$archive_path" -C "$work_directory" \
    --owner=0 --group=0 monitor.db env manifest
chmod 0600 "$archive_path"
printf '%s\n' "$archive_path"
