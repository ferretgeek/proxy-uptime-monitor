#!/usr/bin/env bash
set -euo pipefail

archive=""
bind_host=""
admin_password_file=""
port="18080"

usage() {
    printf '%s\n' \
        '用法：sudo bash scripts/install.sh --archive <发布包.tar.gz> \' \
        '  --bind-host <服务器局域网 IPv4> --admin-password-file <密码文件> [--port 18080]'
}

while (( $# )); do
    case "$1" in
        --archive)
            archive="${2:-}"
            shift 2
            ;;
        --bind-host)
            bind_host="${2:-}"
            shift 2
            ;;
        --admin-password-file)
            admin_password_file="${2:-}"
            shift 2
            ;;
        --port)
            port="${2:-}"
            shift 2
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
done

if (( EUID != 0 )); then
    printf '请使用 sudo 运行此脚本。\n' >&2
    exit 2
fi
if [[ ! -f "$archive" || ! -f "$admin_password_file" ]]; then
    usage >&2
    exit 2
fi
if [[ ! "$bind_host" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] \
    || ! ip -4 -brief address show | grep -Fq "${bind_host}/"; then
    printf '绑定地址不是本机现有的 IPv4 地址。\n' >&2
    exit 2
fi
if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1024 || port > 65535 )); then
    printf '端口必须是 1024～65535 的整数。\n' >&2
    exit 2
fi
if ss -H -ltn "sport = :${port}" | grep -q .; then
    printf '端口 %s 已被占用，安装已停止。\n' "$port" >&2
    exit 3
fi
if [[ -e /opt/airport-monitor/current || -e /etc/airport-monitor/env ]]; then
    printf '检测到现有安装，请改用 scripts/update.sh。\n' >&2
    exit 3
fi
if tar -tzf "$archive" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
    printf '发布包包含不安全路径。\n' >&2
    exit 3
fi

admin_password=""
IFS= read -r admin_password < "$admin_password_file" || true
if (( ${#admin_password} < 14 )); then
    printf '管理员密码至少需要 14 个字符。\n' >&2
    exit 2
fi

if ! id airportmon >/dev/null 2>&1; then
    useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin \
        --user-group airportmon
fi

install -d -o root -g root -m 0755 /opt/airport-monitor/releases
install -d -o root -g root -m 0755 /opt/airport-monitor/bin
install -d -o root -g airportmon -m 0750 /etc/airport-monitor
install -d -o airportmon -g airportmon -m 0700 /var/lib/airport-monitor
install -d -o airportmon -g airportmon -m 0700 /var/log/airport-monitor
install -d -o airportmon -g airportmon -m 0700 /run/airport-monitor
install -d -o root -g root -m 0700 /var/backups/airport-monitor

release_id="$(date -u +%Y%m%dT%H%M%SZ)"
release_directory="/opt/airport-monitor/releases/${release_id}"
if [[ -e "$release_directory" ]]; then
    printf '发布目录已存在，请稍后重试。\n' >&2
    exit 3
fi
install -d -o root -g root -m 0755 "$release_directory"
tar -xzf "$archive" -C "$release_directory" \
    --no-same-owner --no-same-permissions

for required in requirements.txt app/main.py deploy/airport-monitor.service; do
    if [[ ! -f "$release_directory/$required" ]]; then
        printf '发布包缺少 %s。\n' "$required" >&2
        exit 3
    fi
done

python3 -m venv "$release_directory/.venv"
"$release_directory/.venv/bin/python" -m pip install \
    --disable-pip-version-check --no-cache-dir \
    --requirement "$release_directory/requirements.txt"
"$release_directory/.venv/bin/python" -m compileall -q \
    "$release_directory/app"

bash "$release_directory/scripts/install-sing-box.sh"

encryption_key="$("$release_directory/.venv/bin/python" -c \
    'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
session_pepper="$("$release_directory/.venv/bin/python" -c \
    'import secrets; print(secrets.token_urlsafe(48))')"

environment_file="/etc/airport-monitor/env"
umask 0077
printf '%s\n' \
    "AIRPORT_BIND_HOST=${bind_host}" \
    "AIRPORT_PORT=${port}" \
    "AIRPORT_DATA_DIR=/var/lib/airport-monitor" \
    "AIRPORT_RUNTIME_DIR=/run/airport-monitor" \
    "AIRPORT_LOG_DIR=/var/log/airport-monitor" \
    "AIRPORT_SING_BOX=/opt/airport-monitor/bin/sing-box" \
    "AIRPORT_ENCRYPTION_KEY=${encryption_key}" \
    "AIRPORT_SESSION_PEPPER=${session_pepper}" \
    "AIRPORT_ALLOWED_HOSTS=${bind_host},localhost,127.0.0.1" \
    "AIRPORT_LOG_LEVEL=INFO" \
    "AIRPORT_HARDWARE_CPU=" \
    "AIRPORT_HARDWARE_MEMORY=" \
    "AIRPORT_HARDWARE_DISK=" > "$environment_file"
chown root:airportmon "$environment_file"
chmod 0640 "$environment_file"

ln -s "$release_directory" /opt/airport-monitor/current
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
install -d -o root -g root -m 0755 /usr/local/lib/airport-monitor
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

set -a
# shellcheck disable=SC1090
. "$environment_file"
set +a
printf '%s\n' "$admin_password" \
    | runuser --user airportmon --preserve-environment -- \
        env "PYTHONPATH=$release_directory" \
        "$release_directory/.venv/bin/python" -m app.cli init-admin \
        --username admin
unset admin_password encryption_key session_pepper

systemctl daemon-reload
/usr/bin/python3 /usr/local/lib/airport-monitor/hardware_probe.py
systemctl enable airport-monitor.service airport-monitor-health.timer \
    airport-monitor-storage.timer >/dev/null
systemctl start airport-monitor.service
systemctl start airport-monitor-health.timer
systemctl start airport-monitor-storage.timer
/usr/bin/python3 /usr/local/lib/airport-monitor/storage_guard.py

health_url="http://${bind_host}:${port}/api/health"
for _attempt in {1..20}; do
    if curl --fail --silent --show-error \
        --connect-timeout 2 --max-time 5 "$health_url" >/dev/null; then
        printf '平台已安装并通过健康检查。\n'
        exit 0
    fi
    sleep 1
done

printf '平台服务未通过健康检查，请检查 airport-monitor.service。\n' >&2
exit 4
