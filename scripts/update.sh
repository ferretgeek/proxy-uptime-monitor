#!/usr/bin/env bash
set -euo pipefail

archive="${1:-}"
if (( EUID != 0 )); then
    printf '请使用 sudo 运行此脚本。\n' >&2
    exit 2
fi
if [[ ! -f "$archive" ]] \
    || [[ ! -L /opt/airport-monitor/current ]] \
    || [[ ! -f /etc/airport-monitor/env ]]; then
    printf '用法：sudo bash scripts/update.sh <发布包.tar.gz>\n' >&2
    exit 2
fi
if tar -tzf "$archive" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
    printf '发布包包含不安全路径。\n' >&2
    exit 3
fi

previous_release="$(readlink -f /opt/airport-monitor/current)"
release_id="$(date -u +%Y%m%dT%H%M%SZ)"
release_directory="/opt/airport-monitor/releases/${release_id}"
temporary_directory="$(mktemp -d /tmp/airport-monitor-update.XXXXXX)"
release_committed=0
cleanup() {
    if [[ "$temporary_directory" == /tmp/airport-monitor-update.* ]] \
        && [[ -d "$temporary_directory" ]]; then
        rm -rf -- "$temporary_directory"
    fi
    if (( release_committed == 0 )) \
        && [[ "$release_directory" == /opt/airport-monitor/releases/* ]] \
        && [[ "$release_directory" != "$previous_release" ]] \
        && [[ -d "$release_directory" ]] \
        && [[ "$(readlink -f /opt/airport-monitor/current)" != "$release_directory" ]]; then
        rm -rf -- "$release_directory"
    fi
}
trap cleanup EXIT

install -d -o root -g root -m 0755 "$release_directory"
tar -xzf "$archive" -C "$release_directory" \
    --no-same-owner --no-same-permissions
for required in requirements.txt app/main.py deploy/airport-monitor.service; do
    if [[ ! -f "$release_directory/$required" ]]; then
        printf '发布包缺少 %s。\n' "$required" >&2
        exit 3
    fi
done

if [[ -x "$previous_release/.venv/bin/python" ]] \
    && cmp -s "$previous_release/requirements.txt" \
        "$release_directory/requirements.txt"; then
    cp -a -- "$previous_release/.venv" "$release_directory/.venv"
    nice -n 10 "$release_directory/.venv/bin/python" -m pip check
else
    nice -n 10 python3 -m venv "$release_directory/.venv"
    nice -n 10 "$release_directory/.venv/bin/python" -m pip install \
        --disable-pip-version-check --no-cache-dir \
        --requirement "$release_directory/requirements.txt"
fi
nice -n 10 "$release_directory/.venv/bin/python" -m compileall -q \
    "$release_directory/app"
bash "$release_directory/scripts/install-sing-box.sh"

install -d -m 0700 \
    "$temporary_directory/data" \
    "$temporary_directory/run" \
    "$temporary_directory/log"
set -a
# shellcheck disable=SC1091
. /etc/airport-monitor/env
set +a
AIRPORT_DATA_DIR="$temporary_directory/data" \
AIRPORT_RUNTIME_DIR="$temporary_directory/run" \
AIRPORT_LOG_DIR="$temporary_directory/log" \
PYTHONPATH="$release_directory" \
    "$release_directory/.venv/bin/python" -m app.cli verify >/dev/null

backup_archive="$(bash "$release_directory/scripts/backup.sh")"

install -o root -g root -m 0644 \
    "$release_directory/deploy/airport-monitor.service" \
    /etc/systemd/system/airport-monitor.service
install -o root -g root -m 0644 \
    "$release_directory/deploy/airport-monitor-health.service" \
    /etc/systemd/system/airport-monitor-health.service
install -o root -g root -m 0644 \
    "$release_directory/deploy/airport-monitor-health.timer" \
    /etc/systemd/system/airport-monitor-health.timer
install -o root -g root -m 0644 \
    "$release_directory/deploy/airport-monitor-storage.service" \
    /etc/systemd/system/airport-monitor-storage.service
install -o root -g root -m 0644 \
    "$release_directory/deploy/airport-monitor-storage.timer" \
    /etc/systemd/system/airport-monitor-storage.timer
install -o root -g root -m 0755 \
    "$release_directory/deploy/healthcheck.sh" \
    /usr/local/lib/airport-monitor/healthcheck.sh
install -o root -g root -m 0755 \
    "$release_directory/deploy/storage_guard.py" \
    /usr/local/lib/airport-monitor/storage_guard.py
install -o root -g root -m 0755 \
    "$release_directory/deploy/hardware_probe.py" \
    /usr/local/lib/airport-monitor/hardware_probe.py
install -o root -g root -m 0644 \
    "$release_directory/deploy/logrotate.conf" \
    /etc/logrotate.d/airport-monitor

ln -sfnT "$release_directory" /opt/airport-monitor/current
systemctl daemon-reload
systemctl restart airport-monitor.service
/usr/bin/python3 /usr/local/lib/airport-monitor/hardware_probe.py
systemctl enable --now airport-monitor-health.timer >/dev/null
systemctl enable --now airport-monitor-storage.timer >/dev/null
/usr/bin/python3 /usr/local/lib/airport-monitor/storage_guard.py

health_url="http://${AIRPORT_BIND_HOST}:${AIRPORT_PORT}/api/health"
for _attempt in {1..20}; do
    if curl --fail --silent --show-error \
        --connect-timeout 2 --max-time 5 "$health_url" >/dev/null; then
        release_committed=1
        printf '更新完成。更新前备份：%s\n' "$backup_archive"
        exit 0
    fi
    sleep 1
done

ln -sfnT "$previous_release" /opt/airport-monitor/current
systemctl restart airport-monitor.service
printf '新版本健康检查失败，已切回上一版本。更新前备份：%s\n' \
    "$backup_archive" >&2
exit 4
