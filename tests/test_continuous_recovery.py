from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.analytics import _time_reliability
from app.connectivity import ObserverLinkState
from app.database import Database
from app.engine import MonitorEngine


def _seed_node(database: Database, *, next_check_at: str) -> int:
    stamp = "2026-08-01T00:00:00+00:00"
    subscription_id = database.execute(
        "INSERT INTO subscriptions(name,url_encrypted,enabled,"
        "refresh_interval_minutes,created_at,updated_at) "
        "VALUES ('测试','encrypted',1,360,?,?)",
        (stamp, stamp),
    )
    return database.execute(
        "INSERT INTO nodes(subscription_id,fingerprint,name,protocol,"
        "endpoint_mask,config_encrypted,enabled,source_present,current_status,"
        "health_score,next_check_at,circuit_open_until,created_at,updated_at) "
        "VALUES (?,'node','节点','vless','*.example.com:443','encrypted',"
        "1,1,'offline',0,?,'2099-01-01T00:00:00+00:00',?,?)",
        (subscription_id, next_check_at, stamp, stamp),
    )


def _engine(database: Database) -> MonitorEngine:
    return MonitorEngine(
        database,
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        "pepper",
        None,  # type: ignore[arg-type]
    )


def test_scheduler_keeps_due_offline_node_even_with_legacy_circuit(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "monitor.db")
    database.migrate()
    node_id = _seed_node(
        database,
        next_check_at="2000-01-01T00:00:00+00:00",
    )
    engine = _engine(database)
    queued: list[int] = []

    async def fake_enqueue(node_ids, **_kwargs):
        queued.extend(node_ids)
        return "task"

    engine.enqueue_nodes = fake_enqueue  # type: ignore[method-assign]
    asyncio.run(engine._schedule_due_nodes(database.get_settings()))
    assert queued == [node_id]


def test_observer_recovery_clears_circuit_and_forces_future_check_due(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = Database(tmp_path / "monitor.db")
    database.migrate()
    node_id = _seed_node(
        database,
        next_check_at="2099-01-01T00:00:00+00:00",
    )
    database.record_observer_sample(
        "offline",
        "eno1",
        "carrier_down",
        "2026-08-01T00:00:00+00:00",
    )
    monkeypatch.setattr(
        "app.engine.observer_link_state",
        lambda: ObserverLinkState("online", "eno1", "link_ready"),
    )
    engine = _engine(database)
    engine.observer_status = "offline"
    asyncio.run(engine._sample_observer_link())
    node = database.fetch_one(
        "SELECT next_check_at,circuit_open_until FROM nodes WHERE id=?",
        (node_id,),
    )
    assert node is not None
    assert node["next_check_at"] < "2099-01-01T00:00:00+00:00"
    assert node["circuit_open_until"] is None
    event = database.fetch_one(
        "SELECT event_type FROM events ORDER BY id DESC LIMIT 1"
    )
    assert event == {"event_type": "observer_recovery"}


def test_multiday_offline_period_is_counted_until_real_recovery(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "monitor.db")
    database.migrate()
    start = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    end = start + timedelta(days=3)
    node_id = _seed_node(
        database,
        next_check_at=start.isoformat(timespec="seconds"),
    )
    with database.transaction() as connection:
        sampled_at = start
        while sampled_at < end:
            connection.execute(
                "INSERT INTO observer_samples(sampled_at,status,interface,reason) "
                "VALUES (?,'online','eno1','link_ready')",
                (sampled_at.isoformat(timespec="seconds"),),
            )
            sampled_at += timedelta(minutes=2)
        sampled_at = start
        while sampled_at < end:
            elapsed_hours = (sampled_at - start).total_seconds() / 3600
            status = "offline" if 12 <= elapsed_hours < 60 else "online"
            connection.execute(
                "INSERT INTO check_runs(node_id,started_at,finished_at,status,"
                "health_score,node_probe_status,node_probe_successes,"
                "node_probe_samples,attempt_count) "
                "VALUES (?,?,?,?,?,?,?,3,1)",
                (
                    node_id,
                    sampled_at.isoformat(timespec="seconds"),
                    sampled_at.isoformat(timespec="seconds"),
                    status,
                    0.0 if status == "offline" else 100.0,
                    "proxy_error" if status == "offline" else "available",
                    0 if status == "offline" else 3,
                ),
            )
            sampled_at += timedelta(minutes=10)
    reliability = _time_reliability(
        database,
        [node_id],
        start=start,
        end=end,
    )[node_id]
    assert 32.8 <= reliability["availability"] <= 33.5
    assert reliability["coverage_percent"] >= 99.0
    assert reliability["confidence"] == "high"
