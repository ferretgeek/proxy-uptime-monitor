"""为本机 UI 验收写入不含真实凭据的展示数据。"""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / ".local-test" / "data" / "monitor.db"
now = datetime.now(UTC)

with sqlite3.connect(DB) as connection:
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("DELETE FROM subscriptions")
    connection.execute("DELETE FROM observer_samples")
    connection.execute(
        "UPDATE app_settings SET value_json='true' "
        "WHERE key='scheduler_paused'"
    )
    created = now.isoformat(timespec="seconds")
    observer_at = now - timedelta(hours=48)
    while observer_at <= now:
        connection.execute(
            "INSERT INTO observer_samples(sampled_at,status,interface,reason) "
            "VALUES (?,'online','以太网','link_ready')",
            (observer_at.isoformat(timespec="seconds"),),
        )
        observer_at += timedelta(minutes=2)
    subscription_id = connection.execute(
        "INSERT INTO subscriptions(name,url_encrypted,enabled,refresh_interval_minutes,"
        "last_refresh_at,next_refresh_at,node_count,created_at,updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "视觉验收机场",
            "test-only-encrypted",
            1,
            360,
            created,
            (now + timedelta(hours=6)).isoformat(timespec="seconds"),
            6,
            created,
            created,
        ),
    ).lastrowid
    definitions = [
        ("东京 · 海风 01", "vless", "*.example.com:443", "online", 96.0, 168.0, "JP", "日本"),
        ("新加坡 · 赤道 02", "trojan", "*.example.net:443", "online", 91.0, 226.0, "SG", "新加坡"),
        ("洛杉矶 · 黄昏 03", "vmess", "*.example.org:8443", "degraded", 64.0, 482.0, "US", "美国"),
        ("香港 · 中环 04", "shadowsocks", "203.0.*.*:8388", "offline", 18.0, None, "HK", "中国香港"),
        ("首尔 · 云层 05", "hysteria2", "*.example.io:443", "online", 88.0, 195.0, "KR", "韩国"),
        ("法兰克福 · 北线 06", "tuic", "*.example.dev:443", "pending", 0.0, None, "DE", "德国"),
    ]
    node_ids: list[int] = []
    for index, (name, protocol, endpoint, status, health, latency, country_code, region_name) in enumerate(definitions):
        website_latency = round(latency * 4.4, 1) if latency else None
        probe_successes = 3 if status == "online" else 2 if status == "degraded" else 0
        probe_samples = 3 if status in {"online", "degraded"} else 2
        latency_method = "protocol_urltest"
        has_tcp_endpoint = protocol not in {"hysteria2", "tuic"}
        node_values = (
            subscription_id,
            f"fixture-{index}",
            name,
            protocol,
            endpoint,
            "test-only",
            1,
            1,
            status,
            health,
            latency,
            website_latency,
            9.0 if status == "online" else 64.0 if status == "degraded" else None,
            "available" if status == "online" else "unstable" if status == "degraded" else "proxy_error",
            probe_successes,
            probe_samples,
            "Google 204" if status in {"online", "degraded"} else "自动备用",
            latency_method,
            (
                "available"
                if status == "online"
                else "unstable"
                if status == "degraded"
                else "unavailable"
            )
            if has_tcp_endpoint
            else None,
            probe_successes if has_tcp_endpoint else None,
            probe_samples if has_tcp_endpoint else None,
            round(latency * 0.45, 1) if latency and has_tcp_endpoint else None,
            round(latency * 0.5, 1) if latency and has_tcp_endpoint else None,
            2.0 if latency and has_tcp_endpoint else None,
            (now - timedelta(hours=18 + index)).isoformat(timespec="seconds")
            if status in {"online", "degraded"}
            else None,
            (now - timedelta(minutes=4 + index * 3)).isoformat(timespec="seconds")
            if status != "pending"
            else None,
            (now + timedelta(minutes=20 + index)).isoformat(timespec="seconds"),
            4 if status == "offline" else 0,
            "node_probe_unstable" if status == "degraded" else "proxy_error" if status == "offline" else None,
            country_code,
            region_name,
            created,
            created,
        )
        node_id = connection.execute(
            "INSERT INTO nodes(subscription_id,fingerprint,name,protocol,endpoint_mask,"
            "config_encrypted,enabled,source_present,current_status,health_score,"
            "last_latency_ms,last_website_latency_ms,last_node_jitter_ms,"
            "last_node_probe_status,last_node_probe_successes,"
            "last_node_probe_samples,last_node_probe_target,last_node_latency_method,"
            "last_node_endpoint_status,last_node_endpoint_successes,"
            "last_node_endpoint_samples,last_node_endpoint_latency_ms,"
            "last_node_endpoint_latency_p95_ms,last_node_endpoint_jitter_ms,online_since,"
            "last_checked_at,next_check_at,consecutive_failures,last_error_type,"
            "country_code,region_name,created_at,updated_at)"
            f" VALUES ({','.join('?' for _ in node_values)})",
            node_values,
        ).lastrowid
        node_ids.append(node_id)

    services = ("google", "chatgpt", "grok")
    for hour in range(47, -1, -1):
        stamp = (now - timedelta(hours=hour)).isoformat(timespec="seconds")
        for index, node_id in enumerate(node_ids[:5]):
            base = 93 - index * 6 + math.sin((hour + index) / 4) * 5
            status = "online"
            if index == 2 and hour % 5 in {0, 1}:
                status = "degraded"
                base = 58
            if index == 3:
                status = "offline" if hour > 1 else "offline"
                base = 12
            node_latency = None if status == "offline" else 135 + index * 52 + abs(math.sin(hour / 3)) * 70
            website_latency = node_latency * 4.4 if node_latency else None
            probe_successes = 2 if status == "degraded" else 3 if status == "online" else 0
            probe_samples = 3 if status != "offline" else 2
            run_values = (
                node_id,
                stamp,
                stamp,
                status,
                round(base, 1),
                website_latency,
                website_latency,
                website_latency * 1.18 if website_latency else None,
                None if status == "online" else "node_probe_unstable" if status == "degraded" else "proxy_error",
                1,
                "online" if status != "offline" else "offline",
                100.0 if status != "offline" else 0.0,
                None if status != "offline" else "proxy_error",
                "available" if status == "online" else "unstable" if status == "degraded" else "proxy_error",
                node_latency,
                node_latency,
                node_latency * 1.1 if node_latency else None,
                8.0 if status == "online" else 58.0 if status == "degraded" else None,
                probe_successes,
                probe_samples,
                204 if status != "offline" else None,
                "Google 204" if status != "offline" else "自动备用",
                None if status == "online" else "timeout",
                "protocol_urltest",
                (
                    "available"
                    if status == "online"
                    else "unstable"
                    if status == "degraded"
                    else "unavailable"
                )
                if definitions[index][1] not in {"hysteria2", "tuic"}
                else None,
                (
                    probe_successes
                    if definitions[index][1] not in {"hysteria2", "tuic"}
                    else None
                ),
                (
                    probe_samples
                    if definitions[index][1] not in {"hysteria2", "tuic"}
                    else None
                ),
                (
                    round(node_latency * 0.45, 1)
                    if node_latency
                    and definitions[index][1] not in {"hysteria2", "tuic"}
                    else None
                ),
                (
                    round(node_latency * 0.45, 1)
                    if node_latency
                    and definitions[index][1] not in {"hysteria2", "tuic"}
                    else None
                ),
                (
                    round(node_latency * 0.5, 1)
                    if node_latency
                    and definitions[index][1] not in {"hysteria2", "tuic"}
                    else None
                ),
                (
                    2.0
                    if node_latency
                    and definitions[index][1] not in {"hysteria2", "tuic"}
                    else None
                ),
            )
            run_id = connection.execute(
                "INSERT INTO check_runs(node_id,started_at,finished_at,status,health_score,"
                "latency_avg_ms,latency_p50_ms,latency_p95_ms,error_type,attempt_count,"
                "website_status,website_health_score,website_error_type,"
                "node_probe_status,node_latency_ms,node_latency_p50_ms,"
                "node_latency_p95_ms,node_jitter_ms,node_probe_successes,"
                "node_probe_samples,node_probe_http_code,node_probe_target,"
                "node_probe_error_type,node_latency_method,node_endpoint_status,"
                "node_endpoint_successes,node_endpoint_samples,"
                "node_endpoint_latency_ms,node_endpoint_latency_p50_ms,"
                "node_endpoint_latency_p95_ms,node_endpoint_jitter_ms)"
                f" VALUES ({','.join('?' for _ in run_values)})",
                run_values,
            ).lastrowid
            for service_index, service in enumerate(services):
                service_status = "available"
                reachable = 1
                if status == "degraded" and service in {"chatgpt", "grok"}:
                    service_status = (
                        "login_required" if service == "chatgpt" else "service_blocked"
                    )
                    reachable = 1 if service_status == "login_required" else 0
                if status == "offline":
                    service_status = "proxy_error"
                    reachable = 0
                service_latency = website_latency + service_index * 24 if website_latency else None
                connection.execute(
                    "INSERT INTO service_results(check_run_id,service,status,reachable,"
                    "dns_ok,tcp_ok,tls_ok,http_code,latency_ms,dns_ms,tcp_ms,tls_ms,"
                    "ttfb_ms,redirect_count,final_host_class,feature_ok,error_type)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        service,
                        service_status,
                        reachable,
                        int(service_status not in {"dns_error", "proxy_error"}),
                        int(service_status not in {"tcp_error", "proxy_error"}),
                        int(service_status not in {"tls_error", "proxy_error"}),
                        200 if reachable else None,
                        service_latency,
                        0,
                        30 if reachable else None,
                        45 if reachable else None,
                        service_latency * 0.7 if service_latency else None,
                        0,
                        (
                            "target"
                            if service_status == "available"
                            else "login"
                            if service_status == "login_required"
                            else "other"
                        ),
                        int(service_status == "available"),
                        None if service_status == "available" else service_status,
                    ),
                )

    connection.executemany(
        "INSERT INTO events(node_id,event_type,severity,title,detail,created_at,recovered_at)"
        " VALUES (?,?,?,?,?,?,?)",
        [
            (
                node_ids[3],
                "failure",
                "critical",
                "节点转为不可用",
                "代理通道未能建立",
                (now - timedelta(hours=3)).isoformat(timespec="seconds"),
                None,
            ),
            (
                node_ids[2],
                "failure",
                "warning",
                "部分服务可达性下降",
                "Grok 返回服务阻断",
                (now - timedelta(hours=7)).isoformat(timespec="seconds"),
                (now - timedelta(hours=6, minutes=25)).isoformat(timespec="seconds"),
            ),
            (
                node_ids[2],
                "recovery",
                "success",
                "节点已恢复",
                "手动复测通过",
                (now - timedelta(hours=6, minutes=25)).isoformat(timespec="seconds"),
                None,
            ),
            (
                None,
                "subscription_refresh",
                "info",
                "订阅刷新完成",
                "已同步 6 个节点",
                (now - timedelta(minutes=18)).isoformat(timespec="seconds"),
                None,
            ),
        ],
    )
    connection.commit()
