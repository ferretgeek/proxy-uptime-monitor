from pathlib import Path

import pytest

from app.analytics import dashboard, list_nodes
from app.database import Database, iso_now


def _service(service: str) -> dict:
    return {
        "service": service,
        "status": "available",
        "reachable": True,
        "dns_ok": True,
        "tcp_ok": True,
        "tls_ok": True,
        "http_code": 200,
        "latency_ms": 120.0,
        "dns_ms": 0.0,
        "tcp_ms": 20.0,
        "tls_ms": 30.0,
        "ttfb_ms": 80.0,
        "redirect_count": 0,
        "final_host_class": "target",
        "feature_ok": True,
        "error_type": None,
    }


def test_migration_settings_and_recording(tmp_path: Path):
    database = Database(tmp_path / "monitor.db")
    database.migrate()
    settings = database.get_settings()
    assert settings["max_concurrency"] == 3
    assert settings["offline_check_interval_minutes"] == 10
    assert settings["raw_retention_days"] == 20
    assert settings["hourly_retention_days"] == 180
    assert settings["enabled_targets"] == ["google", "chatgpt", "grok"]
    assert settings["node_probe_enabled"] is True
    now = iso_now()
    subscription_id = database.execute(
        "INSERT INTO subscriptions(name,url_encrypted,enabled,refresh_interval_minutes,"
        "created_at,updated_at) VALUES (?,?,?,?,?,?)",
        ("测试订阅", "encrypted", 1, 360, now, now),
    )
    node_id = database.execute(
        "INSERT INTO nodes(subscription_id,fingerprint,name,protocol,endpoint_mask,"
        "config_encrypted,enabled,source_present,current_status,created_at,updated_at)"
        " VALUES (?,?,?,?,?,?,1,1,'pending',?,?)",
        (
            subscription_id,
            "fingerprint",
            "测试节点",
            "vless",
            "*.example.com:443",
            "encrypted",
            now,
            now,
        ),
    )
    result = {
        "started_at": now,
        "finished_at": now,
        "status": "online",
        "health_score": 100.0,
        "latency_avg_ms": 120.0,
        "latency_p50_ms": 120.0,
        "latency_p95_ms": 120.0,
        "error_type": None,
        "attempt_count": 1,
        "website_status": "online",
        "website_health_score": 100.0,
        "website_error_type": None,
        "node_probe_status": "available",
        "node_latency_ms": 228.0,
        "node_latency_p50_ms": 228.0,
        "node_latency_p95_ms": 241.0,
        "node_jitter_ms": 8.5,
        "node_probe_successes": 3,
        "node_probe_samples": 3,
        "node_probe_http_code": 204,
        "node_probe_target": "Google 204",
        "node_probe_error_type": None,
        "node_latency_method": "protocol_urltest",
        "node_endpoint_status": "available",
        "node_endpoint_successes": 3,
        "node_endpoint_samples": 3,
        "node_endpoint_latency_ms": 2.35,
        "node_endpoint_latency_p50_ms": 2.35,
        "node_endpoint_latency_p95_ms": 2.84,
        "node_endpoint_jitter_ms": 0.28,
        "location_attempted": True,
        "location": {
            "country_code": "US",
            "region_name": "美国 · 洛杉矶",
            "exit_ip_mask": "8.8.*.*",
            "provider_count": 3,
        },
        "services": [_service(name) for name in ("google", "chatgpt", "grok", "gemini")],
    }
    database.record_check(
        None,
        node_id,
        result,
        now,
    )
    nodes = list_nodes(database)
    assert len(nodes) == 1
    assert nodes[0]["current_status"] == "online"
    assert nodes[0]["availability_24h"] == 100.0
    assert nodes[0]["last_latency_ms"] == 228.0
    assert nodes[0]["last_website_latency_ms"] == 120.0
    assert nodes[0]["last_node_probe_successes"] == 3
    assert nodes[0]["last_node_latency_method"] == "protocol_urltest"
    assert nodes[0]["last_node_endpoint_successes"] == 3
    assert nodes[0]["last_node_endpoint_latency_ms"] == 2.35
    assert nodes[0]["last_node_endpoint_latency_p95_ms"] == 2.84
    assert nodes[0]["last_node_endpoint_jitter_ms"] == 0.28
    data = dashboard(database)
    assert data["summary"]["nodes_online"] == 1
    assert data["service_rates"]["chatgpt"]["rate"] == 100.0
    assert set(data["service_rates"]) == {"google", "chatgpt", "grok"}
    assert set(nodes[0]["services"]) == {"google", "chatgpt", "grok"}
    assert data["monitoring"]["last_check_at"] == now
    assert data["monitoring"]["check_interval_minutes"] == 15
    assert nodes[0]["country_code"] == "US"
    assert nodes[0]["region_name"] == "美国 · 洛杉矶"
    assert nodes[0]["location_source"] == "auto"
    assert nodes[0]["location_provider_count"] == 3
    assert nodes[0]["exit_ip_mask"] == "8.8.*.*"
    assert database.upsert_hourly_stats("2099-01-01T00:00:00+00:00") == 1
    hourly = database.fetch_one(
        "SELECT node_probe_samples,node_online_samples,node_latency_avg_ms,"
        "latency_avg_ms FROM hourly_stats WHERE node_id=?",
        (node_id,),
    )
    assert hourly == {
        "node_probe_samples": 1,
        "node_online_samples": 1,
        "node_latency_avg_ms": 228.0,
        "latency_avg_ms": 120.0,
    }
    database.execute(
        "UPDATE nodes SET source_present=0,enabled=0 WHERE id=?", (node_id,)
    )
    after_removal = dashboard(database)
    assert after_removal["summary"]["nodes_total"] == 0
    assert "chatgpt" not in after_removal["service_rates"]


def test_settings_validation(tmp_path: Path):
    database = Database(tmp_path / "monitor.db")
    database.migrate()
    with pytest.raises(ValueError):
        database.update_settings({"max_concurrency": 99})
    with pytest.raises(ValueError):
        database.update_settings({"enabled_targets": []})
    with pytest.raises(ValueError):
        database.update_settings({"enabled_targets": ["google", "unknown"]})
    with pytest.raises(ValueError):
        database.update_settings({"node_probe_enabled": "true"})


def test_reschedule_enabled_nodes_only_moves_future_deadlines(tmp_path: Path):
    database = Database(tmp_path / "monitor.db")
    database.migrate()
    now = iso_now()
    subscription_id = database.execute(
        "INSERT INTO subscriptions(name,url_encrypted,enabled,refresh_interval_minutes,"
        "created_at,updated_at) VALUES (?,?,?,?,?,?)",
        ("测试订阅", "encrypted", 1, 360, now, now),
    )
    for fingerprint, enabled, next_check in (
        ("future", 1, "2099-01-01T00:00:00+00:00"),
        ("past", 1, "2000-01-01T00:00:00+00:00"),
        ("disabled", 0, "2099-01-01T00:00:00+00:00"),
    ):
        database.execute(
            "INSERT INTO nodes(subscription_id,fingerprint,name,protocol,endpoint_mask,"
            "config_encrypted,enabled,source_present,current_status,next_check_at,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                subscription_id,
                fingerprint,
                fingerprint,
                "vless",
                "*.example.com:443",
                "encrypted",
                enabled,
                1,
                "pending",
                next_check,
                now,
                now,
            ),
        )
    changed = database.reschedule_enabled_nodes("2026-01-01T00:00:00+00:00")
    assert changed == 1
    rows = {
        row["fingerprint"]: row["next_check_at"]
        for row in database.fetch_all(
            "SELECT fingerprint,next_check_at FROM nodes ORDER BY fingerprint"
        )
    }
    assert rows["future"] == "2026-01-01T00:00:00+00:00"
    assert rows["past"] == "2000-01-01T00:00:00+00:00"
    assert rows["disabled"] == "2099-01-01T00:00:00+00:00"
