#!/usr/bin/env bash
set -euo pipefail

service_name="airport-monitor.service"
counter_file="/run/airport-monitor-health/health.failures"
environment_file="/etc/airport-monitor/env"

set -a
# shellcheck disable=SC1090
. "$environment_file"
set +a

bind_host="${AIRPORT_BIND_HOST:-127.0.0.1}"

# 绑定固定局域网地址时，断开网线会暂时移除该地址。此时原进程仍可在地址
# 恢复后继续服务，不能把“本机暂时没有该地址”误判成应用故障并重启，否则
# 服务会因无法 bind 连续失败并触发 systemd StartLimit。
case "$bind_host" in
    0.0.0.0|127.0.0.1|localhost|::|::1)
        bind_address_ready=true
        ;;
    *)
        if ip -o address show scope global | grep -Fq " ${bind_host}/"; then
            bind_address_ready=true
        else
            bind_address_ready=false
        fi
        ;;
esac

if [[ "$bind_address_ready" != true ]]; then
    printf '0\n' > "$counter_file"
    exit 0
fi

# 主服务可能已经触发启动限流。网络地址恢复后由健康检查清除失败计数并拉起，
# 不再要求管理员手工执行 reset-failed/start。
if ! systemctl is-active --quiet "$service_name"; then
    systemctl reset-failed "$service_name"
    systemctl start "$service_name"
    printf '0\n' > "$counter_file"
    exit 0
fi

health_url="http://${AIRPORT_BIND_HOST}:${AIRPORT_PORT}/api/health"
if curl --fail --silent --show-error \
    --connect-timeout 2 --max-time 5 "$health_url" >/dev/null; then
    printf '0\n' > "$counter_file"
    exit 0
fi

failures=0
if [[ -r "$counter_file" ]]; then
    read -r failures < "$counter_file" || failures=0
fi
if [[ ! "$failures" =~ ^[0-9]+$ ]]; then
    failures=0
fi
failures=$((failures + 1))
printf '%s\n' "$failures" > "$counter_file"

if (( failures >= 3 )); then
    logger --tag airport-monitor-health \
        "监测平台连续三次健康检查失败，正在恢复本平台服务"
    printf '0\n' > "$counter_file"
    systemctl reset-failed "$service_name"
    systemctl restart "$service_name"
fi
