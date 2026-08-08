from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.analytics import _period_score, latency_summary
from app.database import Database


def _seed_node(
    database: Database,
    subscription_id: int,
    *,
    name: str,
    fingerprint: str,
    enabled: bool = True,
) -> int:
    stamp = "2026-07-01T00:00:00+00:00"
    return database.execute(
        "INSERT INTO nodes(subscription_id,fingerprint,name,protocol,"
        "endpoint_mask,config_encrypted,enabled,source_present,current_status,"
        "country_code,region_name,created_at,updated_at) "
        "VALUES (?,?,?,?,?,'encrypted',?,1,'online','KR','韩国',?,?)",
        (
            subscription_id,
            fingerprint,
            name,
            "vless",
            "*.example.com:443",
            int(enabled),
            stamp,
            stamp,
        ),
    )


def test_latency_summary_combines_raw_and_hourly_windows(tmp_path: Path):
    database = Database(tmp_path / "monitor.db")
    database.migrate()
    now = datetime(2026, 7, 27, 0, 0, tzinfo=UTC)
    stamp = now.isoformat(timespec="seconds")
    subscription_id = database.execute(
        "INSERT INTO subscriptions(name,url_encrypted,enabled,"
        "refresh_interval_minutes,created_at,updated_at) VALUES (?,?,?,?,?,?)",
        ("测试订阅", "encrypted", 1, 360, stamp, stamp),
    )
    node_id = _seed_node(
        database,
        subscription_id,
        name="韩国主节点",
        fingerprint="enabled",
    )
    empty_id = _seed_node(
        database,
        subscription_id,
        name="韩国无数据",
        fingerprint="empty",
    )
    disabled_id = _seed_node(
        database,
        subscription_id,
        name="已停用节点",
        fingerprint="disabled",
        enabled=False,
    )

    raw_samples = (
        (6, "online", 200.0, 1000.0),
        (18, "offline", 400.0, 1500.0),
        (50, "online", 600.0, 2000.0),
        (100, "online", 800.0, 3000.0),
        (240, "degraded", 1000.0, 4000.0),
    )
    with database.transaction() as connection:
        for hours, status, node_latency, website_latency in raw_samples:
            sampled_at = (now - timedelta(hours=hours)).isoformat(
                timespec="seconds"
            )
            connection.execute(
                "INSERT INTO check_runs(node_id,started_at,finished_at,status,"
                "health_score,latency_avg_ms,node_probe_status,node_latency_ms,"
                "attempt_count) VALUES (?,?,?,?,?,?,?,?,1)",
                (
                    node_id,
                    sampled_at,
                    sampled_at,
                    status,
                    90.0,
                    website_latency,
                    "available",
                    node_latency,
                ),
            )
        old_bucket = (now - timedelta(hours=600)).replace(
            minute=0,
            second=0,
        ).isoformat(timespec="seconds")
        connection.execute(
            "INSERT INTO hourly_stats(node_id,bucket_at,samples,online_samples,"
            "health_avg,latency_avg_ms,latency_p50_ms,latency_p95_ms,"
            "node_probe_samples,node_online_samples,node_health_avg,"
            "node_latency_avg_ms,node_latency_p50_ms,node_latency_p95_ms) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                node_id,
                old_bucket,
                4,
                3,
                80.0,
                5000.0,
                5000.0,
                5000.0,
                4,
                3,
                80.0,
                1200.0,
                1200.0,
                1200.0,
            ),
        )
        connection.execute(
            "INSERT INTO check_runs(node_id,started_at,finished_at,status,"
            "health_score,latency_avg_ms,node_probe_status,node_latency_ms,"
            "attempt_count) VALUES (?,?,?,?,?,?,?,?,1)",
            (
                disabled_id,
                stamp,
                stamp,
                "online",
                100.0,
                100.0,
                "available",
                100.0,
            ),
        )

    result = latency_summary(database, now=now)
    assert result["total"] == 2
    assert result["summary"]["nodes_scored"] == 1
    assert [item["id"] for item in result["items"]] == [node_id, empty_id]
    assert [window["hours"] for window in result["windows"]] == [
        12,
        24,
        72,
        168,
        360,
        720,
    ]
    assert [window["label"] for window in result["windows"]] == [
        "12 小时",
        "24 小时",
        "72 小时",
        "7 天",
        "15 天",
        "30 天",
    ]

    node = result["items"][0]
    periods = {period["key"]: period for period in node["periods"]}
    assert periods["12h"]["availability"] == 100.0
    assert periods["12h"]["node_latency_ms"] == 200.0
    assert periods["12h"]["website_latency_ms"] == 1000.0
    assert periods["12h"]["node_latency_p95_ms"] == 200.0
    assert periods["12h"]["website_latency_p95_ms"] == 1000.0
    assert periods["12h"]["score"] == _period_score(
        periods["12h"]["availability"],
        periods["12h"]["node_latency_p95_ms"],
        periods["12h"]["website_latency_p95_ms"],
        website_availability=periods["12h"]["website_availability"],
        node_jitter_ms=periods["12h"]["node_jitter_p95_ms"],
        retry_rate=periods["12h"]["retry_rate"],
    )
    assert 55.0 <= periods["24h"]["availability"] <= 65.0
    assert periods["24h"]["node_latency_ms"] == 300.0
    assert periods["24h"]["website_latency_ms"] == 1250.0
    assert periods["24h"]["score"] == _period_score(
        periods["24h"]["availability"],
        periods["24h"]["node_latency_p95_ms"],
        periods["24h"]["website_latency_p95_ms"],
        website_availability=periods["24h"]["website_availability"],
        node_jitter_ms=periods["24h"]["node_jitter_p95_ms"],
        retry_rate=periods["24h"]["retry_rate"],
    )
    assert periods["72h"]["availability_samples"] == 3
    assert periods["168h"]["availability_samples"] == 4
    assert periods["360h"]["availability_samples"] == 5
    assert periods["720h"]["availability_samples"] == 9
    assert periods["720h"]["availability"] is not None
    assert periods["720h"]["node_latency_ms"] == 866.67
    assert periods["720h"]["website_latency_ms"] == 3500.0
    assert periods["720h"]["coverage_percent"] > 0
    assert node["overall_score"] == periods["720h"]["score"]
    assert node["overall_level"] == "critical"

    empty = result["items"][1]
    assert empty["overall_score"] is None
    assert empty["overall_level"] == "unknown"
    assert all(period["score"] is None for period in empty["periods"])
    assert result["summary"]["best_node"] == {
        "id": node_id,
        "name": "韩国主节点",
        "score": node["overall_score"],
    }
    assert result["score_definition"]["availability_weight"] == 45
    assert result["score_definition"]["website_availability_weight"] == 20
    assert result["score_definition"]["missing_values"] == "no_global_reweight"


def test_latency_summary_filters_and_sorts_longest_window(tmp_path: Path):
    database = Database(tmp_path / "monitor.db")
    database.migrate()
    now = datetime(2026, 7, 27, 0, 0, tzinfo=UTC)
    stamp = now.isoformat(timespec="seconds")
    subscription_id = database.execute(
        "INSERT INTO subscriptions(name,url_encrypted,enabled,"
        "refresh_interval_minutes,created_at,updated_at) VALUES (?,?,?,?,?,?)",
        ("线路", "encrypted", 1, 360, stamp, stamp),
    )
    fast = _seed_node(
        database,
        subscription_id,
        name="韩国快速",
        fingerprint="fast",
    )
    slow = _seed_node(
        database,
        subscription_id,
        name="韩国较慢",
        fingerprint="slow",
    )
    with database.transaction() as connection:
        for node_id, node_latency, website_latency in (
            (fast, 180.0, 700.0),
            (slow, 980.0, 4200.0),
        ):
            connection.execute(
                "INSERT INTO check_runs(node_id,started_at,finished_at,status,"
                "health_score,latency_avg_ms,node_probe_status,node_latency_ms,"
                "attempt_count) VALUES (?,?,?,?,?,?,?,?,1)",
                (
                    node_id,
                    stamp,
                    stamp,
                    "online",
                    100.0,
                    website_latency,
                    "available",
                    node_latency,
                ),
            )

    slowest_first = latency_summary(
        database,
        now=now,
        sort="node_latency",
        direction="desc",
    )
    assert [item["id"] for item in slowest_first["items"]] == [slow, fast]
    filtered = latency_summary(
        database,
        now=now,
        search="快速",
        country="KR",
    )
    assert filtered["total"] == 1
    assert filtered["items"][0]["id"] == fast
    assert filtered["facets"]["countries"] == [
        {"code": "KR", "name": "韩国", "count": 2}
    ]


def test_latency_summary_includes_exact_720_hour_boundary(tmp_path: Path):
    database = Database(tmp_path / "monitor.db")
    database.migrate()
    now = datetime(2026, 7, 27, 0, 0, tzinfo=UTC)
    stamp = now.isoformat(timespec="seconds")
    subscription_id = database.execute(
        "INSERT INTO subscriptions(name,url_encrypted,enabled,"
        "refresh_interval_minutes,created_at,updated_at) VALUES (?,?,?,?,?,?)",
        ("边界线路", "encrypted", 1, 360, stamp, stamp),
    )
    node_id = _seed_node(
        database,
        subscription_id,
        name="边界节点",
        fingerprint="boundary",
    )
    with database.transaction() as connection:
        for seconds in (720 * 3600, 720 * 3600 + 1):
            sampled_at = (now - timedelta(seconds=seconds)).isoformat(
                timespec="seconds"
            )
            connection.execute(
                "INSERT INTO check_runs(node_id,started_at,finished_at,status,"
                "health_score,latency_avg_ms,node_probe_status,node_latency_ms,"
                "attempt_count) VALUES (?,?,?,?,?,?,?,?,1)",
                (
                    node_id,
                    sampled_at,
                    sampled_at,
                    "online",
                    100.0,
                    900.0,
                    "available",
                    250.0,
                ),
            )
    result = latency_summary(database, now=now)
    period = result["items"][0]["periods"][-1]
    assert period["key"] == "720h"
    assert period["availability_samples"] == 1
    assert period["node_latency_samples"] == 1
    assert period["website_latency_samples"] == 1


def test_latency_score_does_not_reweight_missing_metrics_upward():
    assert _period_score(100.0, None, 1000.0) == 55.0
    assert _period_score(50.0, None, 1000.0) == 32.5
    assert (
        _period_score(
            100.0,
            300.0,
            1000.0,
            website_availability=100.0,
            node_jitter_ms=20.0,
            retry_rate=0.0,
        )
        == 100.0
    )
    assert _period_score(None, None, None) is None
