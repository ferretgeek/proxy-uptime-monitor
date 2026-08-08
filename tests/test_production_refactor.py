from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path

from app.analytics import node_page, node_trend
from app.config import AppConfig
from app.database import Database, iso_now, parse_time, utc_now
from app.locations import infer_location, mask_public_ip, resolve_exit_location
from app.storage import GIB, StorageManager
from app.targets import DEFAULT_TARGET_KEYS, TARGETS, public_target_catalog


def _seed_node(database: Database, name: str, status: str = "online") -> int:
    now = iso_now()
    subscription_id = database.fetch_one(
        "SELECT id FROM subscriptions LIMIT 1"
    )
    if subscription_id:
        sub_id = int(subscription_id["id"])
    else:
        sub_id = database.execute(
            "INSERT INTO subscriptions(name,url_encrypted,enabled,"
            "refresh_interval_minutes,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            ("测试订阅", "encrypted", 1, 360, now, now),
        )
    code, region = infer_location(name)
    return database.execute(
        "INSERT INTO nodes(subscription_id,fingerprint,name,protocol,endpoint_mask,"
        "config_encrypted,enabled,source_present,current_status,health_score,"
        "country_code,region_name,created_at,updated_at) "
        "VALUES (?,?,?,?,?,'encrypted',1,1,?,?,?, ?,?,?)",
        (
            sub_id,
            f"fp-{name}",
            name,
            "vless",
            "*.example.com:443",
            status,
            95 if status == "online" else 0,
            code,
            region,
            now,
            now,
        ),
    )


def test_target_catalog_is_complete_and_defaults_are_unchanged():
    catalog = public_target_catalog()
    assert len(catalog) == 15
    assert tuple(item["key"] for item in catalog if item["default_enabled"]) == (
        DEFAULT_TARGET_KEYS
    )
    assert all(TARGETS[item["key"]]["url"].startswith("https://") for item in catalog)


def test_location_inference_is_conservative():
    assert infer_location("泰国 AnyTLS") == ("TH", "泰国")
    assert infer_location("Tokyo premium") == ("JP", "日本")
    assert infer_location("VLESS-198-TCP") == ("ZZ", "未知地区")


def test_exit_location_requires_multiple_sources_and_masks_ip():
    result = resolve_exit_location(
        "198.51.100.42",
        [
            {"country_code": "US"},
            {
                "country_code": "US",
                "country": "United States",
                "region": "California",
                "city": "Los Angeles",
            },
            {
                "country_code": "US",
                "country": "United States",
                "region": "California",
                "city": "Los Angeles",
            },
        ],
    )
    # 文档保留地址不属于公网，必须拒绝，避免把测试或内网地址写成真实地区。
    assert result is None
    assert mask_public_ip("192.168.1.10") is None
    public_result = resolve_exit_location(
        "8.8.8.8",
        [
            {"country_code": "US"},
            {
                "country_code": "US",
                "country": "United States",
                "region": "California",
                "city": "Los Angeles",
            },
            {
                "country_code": "US",
                "country": "United States",
                "region": "California",
                "city": "Los Angeles",
            },
        ],
    )
    assert public_result == {
        "country_code": "US",
        "region_name": "美国 · 洛杉矶",
        "exit_ip_mask": "8.8.*.*",
        "provider_count": 3,
    }
    assert (
        resolve_exit_location(
            "8.8.8.8",
            [{"country_code": "US"}, {"country_code": "DE"}],
        )
        is None
    )


def test_node_page_filters_paginates_and_trend_is_bounded(tmp_path: Path):
    database = Database(tmp_path / "monitor.db")
    database.migrate()
    first = _seed_node(database, "东京 01")
    paused = _seed_node(database, "泰国 02", "offline")
    database.execute("UPDATE nodes SET enabled=0 WHERE id=?", (paused,))
    now = utc_now()
    with database.transaction() as connection:
        for index in range(260):
            stamp = (now - timedelta(minutes=index * 15)).isoformat(
                timespec="seconds"
            )
            connection.execute(
                "INSERT INTO check_runs(node_id,started_at,finished_at,status,"
                "health_score,latency_avg_ms,node_probe_status,node_latency_ms,"
                "node_probe_successes,node_probe_samples,attempt_count) "
                "VALUES (?,?,?,?,?,?,'available',?,3,3,1)",
                (
                    first,
                    stamp,
                    stamp,
                    "online",
                    90,
                    120 + index % 30,
                    210 + index % 20,
                ),
            )
    page = node_page(
        database,
        page=1,
        page_size=10,
        country="JP",
        search="东京",
    )
    assert page["total"] == 1
    assert page["items"][0]["region_name"] == "日本"
    paused_page = node_page(database, status="paused")
    assert paused_page["total"] == 1
    assert paused_page["items"][0]["enabled"] is False
    assert paused_page["items"][0]["level"] == "unknown"
    assert paused_page["facets"]["statuses"]["paused"] == 1
    homepage_page = node_page(database, enabled_only=True)
    assert homepage_page["total"] == 1
    assert homepage_page["items"][0]["id"] == first
    assert "paused" not in homepage_page["facets"]["statuses"]
    points = node_trend(database, first, 30)
    assert 1 <= len(points) <= 192
    assert all(
        "latency_ms" in point
        and "website_latency_ms" in point
        and "health" in point
        for point in points
    )
    assert any(point["latency_ms"] is not None for point in points)
    assert any(point["website_latency_ms"] is not None for point in points)


def test_node_page_sorts_two_latency_metrics_independently_and_keeps_missing_last(
    tmp_path: Path,
):
    database = Database(tmp_path / "monitor.db")
    database.migrate()
    fast_website = _seed_node(database, "网页快、节点慢")
    fast_node = _seed_node(database, "节点快、网页慢")
    missing = _seed_node(database, "尚无延迟")
    database.execute(
        "UPDATE nodes SET last_latency_ms=420,last_website_latency_ms=120 "
        "WHERE id=?",
        (fast_website,),
    )
    database.execute(
        "UPDATE nodes SET last_latency_ms=95,last_website_latency_ms=680 "
        "WHERE id=?",
        (fast_node,),
    )

    by_node = node_page(database, sort="node_latency", direction="asc")
    assert [item["id"] for item in by_node["items"]] == [
        fast_node,
        fast_website,
        missing,
    ]
    by_website = node_page(database, sort="website_latency", direction="asc")
    assert [item["id"] for item in by_website["items"]] == [
        fast_website,
        fast_node,
        missing,
    ]
    descending = node_page(database, sort="node_latency", direction="desc")
    assert [item["id"] for item in descending["items"]] == [
        fast_website,
        fast_node,
        missing,
    ]


def test_old_default_retention_migrates_to_twenty_days(tmp_path: Path):
    path = tmp_path / "legacy.db"
    migrations = Path(__file__).resolve().parents[1] / "app" / "migrations"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            (migrations / "001_initial.sql").read_text(encoding="utf-8")
        )
        connection.execute(
            "CREATE TABLE schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES ('001_initial',?)", (iso_now(),)
        )
        connection.execute(
            "INSERT INTO app_settings(key,value_json,updated_at) VALUES (?,?,?)",
            ("raw_retention_days", json.dumps(7), iso_now()),
        )
    database = Database(path)
    database.migrate()
    assert database.get_settings()["raw_retention_days"] == 20
    columns = {
        row["name"]
        for row in database.fetch_all("PRAGMA table_info(nodes)")
    }
    assert {
        "location_source",
        "location_checked_at",
        "location_provider_count",
        "exit_ip_mask",
        "last_node_endpoint_latency_ms",
        "last_node_endpoint_latency_p95_ms",
        "last_node_endpoint_jitter_ms",
    }.issubset(columns)
    metric_columns = {
        row["name"]
        for row in database.fetch_all("PRAGMA table_info(system_metrics)")
    }
    assert {"cpu_temperature_c", "disk_temperature_c"}.issubset(metric_columns)
    run_columns = {
        row["name"]
        for row in database.fetch_all("PRAGMA table_info(check_runs)")
    }
    assert {
        "website_status",
        "node_probe_status",
        "node_latency_ms",
        "node_jitter_ms",
        "node_probe_successes",
        "node_probe_samples",
        "node_latency_method",
        "node_endpoint_status",
        "node_endpoint_successes",
        "node_endpoint_samples",
        "node_endpoint_latency_ms",
        "node_endpoint_latency_p50_ms",
        "node_endpoint_latency_p95_ms",
        "node_endpoint_jitter_ms",
    }.issubset(run_columns)


def test_tcp_entry_latency_is_moved_out_of_primary_protocol_path(tmp_path: Path):
    path = tmp_path / "endpoint-latency.db"
    migrations = Path(__file__).resolve().parents[1] / "app" / "migrations"
    now = iso_now()
    legacy_versions = [f"{index:03d}_{name}" for index, name in (
        (1, "initial"),
        (2, "production_refactor"),
        (3, "exit_location"),
        (4, "external_reachability"),
        (5, "hardware_metrics"),
        (6, "extend_admin_sessions"),
        (7, "dual_latency"),
        (8, "endpoint_latency_semantics"),
    )]
    with sqlite3.connect(path) as connection:
        for version in legacy_versions:
            connection.executescript(
                (migrations / f"{version}.sql").read_text(encoding="utf-8")
            )
        connection.execute(
            "CREATE TABLE schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO schema_migrations VALUES (?,?)",
            ((version, now) for version in legacy_versions),
        )
        subscription_id = connection.execute(
            "INSERT INTO subscriptions(name,url_encrypted,created_at,updated_at) "
            "VALUES ('测试订阅','encrypted',?,?)",
            (now, now),
        ).lastrowid
        node_id = connection.execute(
            "INSERT INTO nodes(subscription_id,fingerprint,name,protocol,"
            "endpoint_mask,config_encrypted,current_status,health_score,"
            "last_latency_ms,last_node_jitter_ms,last_node_probe_status,"
            "last_node_probe_successes,last_node_probe_samples,last_node_probe_target,"
            "last_node_latency_method,last_node_endpoint_status,"
            "last_node_endpoint_successes,last_node_endpoint_samples,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,'online',100,2.35,0.28,'available',3,3,"
            "'Cloudflare 204','tcp_connect','available',3,3,?,?)",
            (
                subscription_id,
                "azure-korea",
                "Azure韩国 AnyTLS",
                "anytls",
                "*.example.com:443",
                "encrypted",
                now,
                now,
            ),
        ).lastrowid
        connection.execute(
            "INSERT INTO check_runs(node_id,started_at,finished_at,status,health_score,"
            "node_probe_status,node_latency_ms,node_latency_p50_ms,node_latency_p95_ms,"
            "node_jitter_ms,node_probe_successes,node_probe_samples,node_probe_target,"
            "node_latency_method,node_endpoint_status,node_endpoint_successes,"
            "node_endpoint_samples) VALUES (?, ?,?,'online',100,'available',"
            "2.35,2.35,2.84,0.28,3,3,'Cloudflare 204','tcp_connect','available',3,3)",
            (node_id, now, now),
        )
        connection.execute(
            "INSERT INTO hourly_stats(node_id,bucket_at,samples,online_samples,"
            "health_avg,node_probe_samples,node_online_samples,node_health_avg,"
            "node_latency_avg_ms,node_latency_p50_ms,node_latency_p95_ms) "
            "VALUES (?,?,1,1,100,1,1,100,2.35,2.35,2.84)",
            (node_id, now),
        )

    database = Database(path)
    database.migrate()
    node = database.fetch_one(
        "SELECT last_latency_ms,last_node_jitter_ms,last_node_latency_method,"
        "last_node_endpoint_latency_ms,last_node_endpoint_jitter_ms FROM nodes "
        "WHERE id=?",
        (node_id,),
    )
    assert node == {
        "last_latency_ms": None,
        "last_node_jitter_ms": None,
        "last_node_latency_method": None,
        "last_node_endpoint_latency_ms": 2.35,
        "last_node_endpoint_jitter_ms": 0.28,
    }
    run = database.fetch_one(
        "SELECT node_latency_ms,node_latency_method,node_endpoint_latency_ms,"
        "node_endpoint_latency_p50_ms,node_endpoint_latency_p95_ms,"
        "node_endpoint_jitter_ms FROM check_runs WHERE node_id=?",
        (node_id,),
    )
    assert run == {
        "node_latency_ms": None,
        "node_latency_method": "endpoint_only_legacy",
        "node_endpoint_latency_ms": 2.35,
        "node_endpoint_latency_p50_ms": 2.35,
        "node_endpoint_latency_p95_ms": 2.84,
        "node_endpoint_jitter_ms": 0.28,
    }
    hourly = database.fetch_one(
        "SELECT node_latency_avg_ms,node_latency_p50_ms,node_latency_p95_ms "
        "FROM hourly_stats WHERE node_id=?",
        (node_id,),
    )
    assert hourly == {
        "node_latency_avg_ms": None,
        "node_latency_p50_ms": None,
        "node_latency_p95_ms": None,
    }


def test_existing_active_sessions_extend_to_thirty_days(tmp_path: Path):
    database = Database(tmp_path / "session-upgrade.db")
    database.migrate()
    now = iso_now()
    database.create_admin("admin", "hashed")
    admin = database.fetch_one("SELECT id FROM admins WHERE username='admin'")
    database.execute(
        "INSERT INTO sessions(token_hash,admin_id,csrf_hash,created_at,expires_at,"
        "last_seen_at,remote_fingerprint) VALUES (?,?,?,?,?,?,?)",
        (
            "session",
            admin["id"],
            "csrf",
            now,
            (utc_now() + timedelta(hours=1)).isoformat(timespec="seconds"),
            now,
            "fingerprint",
        ),
    )
    database.execute(
        "DELETE FROM schema_migrations WHERE version='006_extend_admin_sessions'"
    )
    database.migrate()
    extended = parse_time(
        database.fetch_one(
            "SELECT expires_at FROM sessions WHERE token_hash='session'"
        )["expires_at"]
    )
    assert extended is not None
    assert extended - utc_now() > timedelta(days=29, hours=23)


def test_legacy_challenge_results_migrate_to_external_reachability(
    tmp_path: Path,
):
    path = tmp_path / "legacy-challenge.db"
    migrations = Path(__file__).resolve().parents[1] / "app" / "migrations"
    now = iso_now()
    with sqlite3.connect(path) as connection:
        for version in (
            "001_initial",
            "002_production_refactor",
            "003_exit_location",
        ):
            connection.executescript(
                (migrations / f"{version}.sql").read_text(encoding="utf-8")
            )
        connection.execute(
            "CREATE TABLE schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO schema_migrations VALUES (?,?)",
            (
                ("001_initial", now),
                ("002_production_refactor", now),
                ("003_exit_location", now),
            ),
        )
        subscription_id = connection.execute(
            "INSERT INTO subscriptions(name,url_encrypted,created_at,updated_at) "
            "VALUES ('旧订阅','encrypted',?,?)",
            (now, now),
        ).lastrowid
        node_id = connection.execute(
            "INSERT INTO nodes(subscription_id,fingerprint,name,protocol,"
            "endpoint_mask,config_encrypted,current_status,health_score,"
            "last_error_type,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,'degraded',94,'captcha',?,?)",
            (
                subscription_id,
                "legacy-node",
                "旧节点",
                "anytls",
                "*.example.com:443",
                "encrypted",
                now,
                now,
            ),
        ).lastrowid
        run_id = connection.execute(
            "INSERT INTO check_runs(node_id,started_at,finished_at,status,"
            "health_score,latency_avg_ms,error_type) "
            "VALUES (?,?,?,'degraded',94,180,'captcha')",
            (node_id, now, now),
        ).lastrowid
        for service, status in (
            ("google", "available"),
            ("chatgpt", "captcha"),
            ("grok", "captcha"),
        ):
            connection.execute(
                "INSERT INTO service_results(check_run_id,service,status,"
                "reachable,dns_ok,tcp_ok,tls_ok,http_code,latency_ms,"
                "redirect_count,feature_ok,error_type) "
                "VALUES (?,?,?,1,1,1,1,200,180,0,?,?)",
                (
                    run_id,
                    service,
                    status,
                    int(status == "available"),
                    None if status == "available" else status,
                ),
            )
    database = Database(path)
    database.migrate()
    run = database.fetch_one(
        "SELECT status,health_score,error_type FROM check_runs WHERE id=?",
        (run_id,),
    )
    node = database.fetch_one(
        "SELECT current_status,health_score,last_error_type FROM nodes WHERE id=?",
        (node_id,),
    )
    services = database.fetch_all(
        "SELECT status,reachable,error_type FROM service_results "
        "WHERE check_run_id=?",
        (run_id,),
    )
    assert run == {
        "status": "online",
        "health_score": 100.0,
        "error_type": None,
    }
    assert node == {
        "current_status": "online",
        "health_score": 100.0,
        "last_error_type": None,
    }
    assert all(
        item == {"status": "available", "reachable": 1, "error_type": None}
        for item in services
    )


def test_storage_limits_are_exact_and_snapshot_counts_runtime_data(tmp_path: Path):
    config = AppConfig(
        bind_host="127.0.0.1",
        port=18080,
        data_dir=tmp_path / "data",
        runtime_dir=tmp_path / "run",
        log_dir=tmp_path / "log",
        sing_box_path=tmp_path / "sing-box",
        encryption_key="test",
        session_pepper="test",
        allowed_hosts=("127.0.0.1",),
        log_level="INFO",
    )
    config.ensure_runtime_directories()
    (config.data_dir / "monitor.db").write_bytes(b"x" * 2048)
    (config.log_dir / "app.log").write_bytes(b"x" * 1024)
    snapshot = StorageManager(config).snapshot()
    assert snapshot.database_bytes == 2048
    assert snapshot.log_bytes == 1024
    assert snapshot.log_hard_bytes == 10 * GIB
    assert snapshot.total_hard_bytes == 15 * GIB


def test_hardware_profile_is_public_deployment_metadata(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AIRPORT_ENCRYPTION_KEY", "test-key")
    monkeypatch.setenv("AIRPORT_SESSION_PEPPER", "test-pepper")
    monkeypatch.setenv("AIRPORT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AIRPORT_HARDWARE_CPU", " Intel Core i7-8700T ES ")
    monkeypatch.setenv("AIRPORT_HARDWARE_MEMORY", "DDR4-2666 8 GB × 2")
    monkeypatch.setenv("AIRPORT_HARDWARE_DISK", "英睿达 MX500 500 GB")
    config = AppConfig.from_env()
    assert config.hardware_profile == {
        "cpu": "Intel Core i7-8700T ES",
        "memory": "DDR4-2666 8 GB × 2",
        "disk": "英睿达 MX500 500 GB",
    }
