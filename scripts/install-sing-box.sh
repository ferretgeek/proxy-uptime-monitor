#!/usr/bin/env bash
set -euo pipefail

sing_box_version="1.13.14"
archive_name="sing-box-${sing_box_version}-linux-amd64.tar.gz"
download_url="https://github.com/SagerNet/sing-box/releases/download/v${sing_box_version}/${archive_name}"
expected_sha256="f48703461a15476951ac4967cdad339d986f4b8096b4eb3ff0829a500502d697"
install_path="/opt/airport-monitor/bin/sing-box"

if (( EUID != 0 )); then
    printf '请使用 sudo 运行此脚本。\n' >&2
    exit 2
fi

if [[ -x "$install_path" ]] \
    && "$install_path" version 2>/dev/null | head -n 1 \
        | grep -Fq "sing-box version ${sing_box_version}"; then
    printf 'sing-box %s 已就绪。\n' "$sing_box_version"
    exit 0
fi

temporary_directory="$(mktemp -d /tmp/airport-monitor-sing-box.XXXXXX)"
cleanup() {
    if [[ "$temporary_directory" == /tmp/airport-monitor-sing-box.* ]] \
        && [[ -d "$temporary_directory" ]]; then
        rm -rf -- "$temporary_directory"
    fi
}
trap cleanup EXIT

curl --fail --location --silent --show-error \
    --retry 3 --retry-delay 2 --connect-timeout 10 --max-time 180 \
    "$download_url" --output "$temporary_directory/$archive_name"

printf '%s  %s\n' "$expected_sha256" "$temporary_directory/$archive_name" \
    | sha256sum --check --status

tar -xzf "$temporary_directory/$archive_name" \
    -C "$temporary_directory" --no-same-owner
source_binary="$temporary_directory/sing-box-${sing_box_version}-linux-amd64/sing-box"
if [[ ! -x "$source_binary" ]]; then
    printf '官方 sing-box 压缩包结构不符合预期。\n' >&2
    exit 3
fi

install -d -m 0755 /opt/airport-monitor/bin
install -o root -g root -m 0755 "$source_binary" "$install_path"
"$install_path" version | head -n 1
