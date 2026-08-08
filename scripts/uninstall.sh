#!/usr/bin/env bash
set -euo pipefail

confirmation="${1:-}"
purge_flag="${2:-}"
purge_confirmation="${3:-}"

if (( EUID != 0 )); then
    printf '请使用 sudo 运行此脚本。\n' >&2
    exit 2
fi
if [[ "$confirmation" != "--confirm-uninstall" ]]; then
    printf '%s\n' \
        '用法：sudo bash scripts/uninstall.sh --confirm-uninstall' \
        '彻底清除数据：再追加 --purge-data --confirm-purge' >&2
    exit 2
fi

backup_archive=""
if [[ -x /opt/airport-monitor/current/.venv/bin/python ]] \
    && [[ -f /var/lib/airport-monitor/monitor.db ]]; then
    backup_archive="$(bash /opt/airport-monitor/current/scripts/backup.sh)"
fi

systemctl disable --now airport-monitor-health.timer \
    airport-monitor-storage.timer >/dev/null 2>&1 || true
systemctl stop airport-monitor.service >/dev/null 2>&1 || true
systemctl disable airport-monitor.service >/dev/null 2>&1 || true
rm -f -- \
    /etc/systemd/system/airport-monitor.service \
    /etc/systemd/system/airport-monitor-health.service \
    /etc/systemd/system/airport-monitor-health.timer \
    /etc/systemd/system/airport-monitor-storage.service \
    /etc/systemd/system/airport-monitor-storage.timer \
    /etc/logrotate.d/airport-monitor \
    /usr/local/lib/airport-monitor/healthcheck.sh \
    /usr/local/lib/airport-monitor/hardware_probe.py \
    /usr/local/lib/airport-monitor/storage_guard.py
rmdir /usr/local/lib/airport-monitor 2>/dev/null || true
rm -rf -- /opt/airport-monitor
systemctl daemon-reload

if [[ "$purge_flag" == "--purge-data" ]]; then
    if [[ "$purge_confirmation" != "--confirm-purge" ]]; then
        printf '未提供 --confirm-purge，配置和数据已保留。\n' >&2
        exit 3
    fi
    for exact_target in \
        /etc/airport-monitor \
        /var/lib/airport-monitor \
        /var/log/airport-monitor \
        /run/airport-monitor; do
        case "$exact_target" in
            /etc/airport-monitor|/var/lib/airport-monitor|\
            /var/log/airport-monitor|/run/airport-monitor)
                rm -rf -- "$exact_target"
                ;;
            *)
                printf '拒绝清理意外路径：%s\n' "$exact_target" >&2
                exit 4
                ;;
        esac
    done
    if id airportmon >/dev/null 2>&1; then
        userdel airportmon
    fi
    printf '程序、配置和运行数据均已移除。'
else
    printf '程序和系统服务已移除；配置与数据仍保留。'
fi
if [[ -n "$backup_archive" ]]; then
    printf ' 卸载前备份：%s' "$backup_archive"
fi
printf '\n'
