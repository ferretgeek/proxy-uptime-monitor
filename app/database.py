from __future__ import annotations

import csv
import io
import json
import math
import sqlite3
import statistics
import threading
from collections import defaultdict
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from .locations import infer_location, normalize_detected_country_code
from .targets import DEFAULT_TARGET_KEYS, normalize_target_keys


def _safe_csv_cell(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    candidate = value.lstrip(" \t\r\n")
    if candidate.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")


def iso_after(**kwargs: int | float) -> str:
    return (utc_now() + timedelta(**kwargs)).isoformat(timespec="seconds")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


DEFAULT_MONITOR_SETTINGS: dict[str, Any] = {
    "check_interval_minutes": 15,
    "offline_check_interval_minutes": 10,
    "timeout_seconds": 18,
    "retry_count": 1,
    "max_concurrency": 3,
    "jitter_seconds": 60,
    "scheduler_paused": False,
    "raw_retention_days": 20,
    "hourly_retention_days": 180,
    "enabled_targets": list(DEFAULT_TARGET_KEYS),
    "node_probe_enabled": True,
}


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._write_lock = threading.RLock()
        self.migrations_dir = Path(__file__).resolve().parent / "migrations"

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path, timeout=5, isolation_level=None, check_same_thread=False
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.execute("PRAGMA cache_size = -8192")
        connection.execute("PRAGMA mmap_size = 67108864")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            connection = self.connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {
                row["version"]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            for migration in sorted(self.migrations_dir.glob("*.sql")):
                version = migration.stem
                if version in applied:
                    continue
                script = migration.read_text(encoding="utf-8")
                connection.executescript(script)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, iso_now()),
                )
            connection.execute(
                "UPDATE tasks SET status='interrupted', finished_at=?, "
                "message='服务重启，未完成任务已安全中止' "
                "WHERE status IN ('queued','running')",
                (iso_now(),),
            )
            for key, value in DEFAULT_MONITOR_SETTINGS.items():
                connection.execute(
                    "INSERT OR IGNORE INTO app_settings(key, value_json, updated_at) "
                    "VALUES (?, ?, ?)",
                    (key, json.dumps(value), iso_now()),
                )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(nodes)").fetchall()
            }
            if {"country_code", "region_name"}.issubset(columns):
                for row in connection.execute(
                    "SELECT id,name,endpoint_mask,country_code FROM nodes "
                    "WHERE country_code='ZZ' OR country_code IS NULL"
                ).fetchall():
                    code, region = infer_location(row["name"], row["endpoint_mask"])
                    if code != "ZZ":
                        connection.execute(
                            "UPDATE nodes SET country_code=?,region_name=?,"
                            "location_source=CASE WHEN location_source IN "
                            "('auto','manual') THEN location_source ELSE 'name' END "
                            "WHERE id=?",
                            (code, region, row["id"]),
                        )
            connection.execute(
                "INSERT OR IGNORE INTO notification_config"
                "(id, enabled, event_types_json, cooldown_minutes, updated_at) "
                "VALUES (1, 0, '[\"failure\",\"recovery\"]', 30, ?)",
                (iso_now(),),
            )

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        connection = self.connect()
        try:
            row = connection.execute(sql, params).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def fetch_all(
        self, sql: str, params: Sequence[Any] = ()
    ) -> list[dict[str, Any]]:
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]
        finally:
            connection.close()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self.transaction() as connection:
            cursor = connection.execute(sql, params)
            return int(cursor.lastrowid or 0)

    def execute_many(self, sql: str, values: Iterable[Sequence[Any]]) -> None:
        with self.transaction() as connection:
            connection.executemany(sql, values)

    def get_settings(self) -> dict[str, Any]:
        result = dict(DEFAULT_MONITOR_SETTINGS)
        for row in self.fetch_all("SELECT key, value_json FROM app_settings"):
            if row["key"] not in DEFAULT_MONITOR_SETTINGS:
                continue
            try:
                result[row["key"]] = json.loads(row["value_json"])
            except json.JSONDecodeError:
                continue
        return result

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        allowed = set(DEFAULT_MONITOR_SETTINGS)
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"不支持的设置项：{', '.join(sorted(unknown))}")
        current = self.get_settings()
        current.update(changes)
        self._validate_settings(current)
        now = iso_now()
        with self.transaction() as connection:
            for key, value in changes.items():
                connection.execute(
                    "INSERT INTO app_settings(key, value_json, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, "
                    "updated_at=excluded.updated_at",
                    (key, json.dumps(value), now),
                )
        return self.get_settings()

    def reschedule_enabled_nodes(
        self,
        due_at: str | None = None,
        *,
        clear_circuit: bool = False,
    ) -> int:
        due_at = due_at or iso_now()
        with self.transaction() as connection:
            if clear_circuit:
                cursor = connection.execute(
                    "UPDATE nodes SET "
                    "next_check_at=CASE "
                    "WHEN next_check_at IS NULL OR next_check_at>? "
                    "THEN ? ELSE next_check_at END,"
                    "circuit_open_until=NULL,updated_at=? "
                    "WHERE enabled=1 AND source_present=1",
                    (due_at, due_at, due_at),
                )
                return int(cursor.rowcount)
            cursor = connection.execute(
                "UPDATE nodes SET next_check_at=?,updated_at=? "
                "WHERE enabled=1 AND source_present=1 "
                "AND (next_check_at IS NULL OR next_check_at>?)",
                (due_at, due_at, due_at),
            )
            return int(cursor.rowcount)

    @staticmethod
    def _validate_settings(settings: dict[str, Any]) -> None:
        ranges = {
            "check_interval_minutes": (5, 1440),
            "offline_check_interval_minutes": (5, 1440),
            "timeout_seconds": (5, 60),
            "retry_count": (0, 3),
            "max_concurrency": (1, 8),
            "jitter_seconds": (0, 900),
            "raw_retention_days": (2, 30),
            "hourly_retention_days": (30, 730),
        }
        for key, (minimum, maximum) in ranges.items():
            value = settings.get(key)
            if not isinstance(value, int) or not minimum <= value <= maximum:
                raise ValueError(f"{key} 必须是 {minimum}～{maximum} 的整数")
        if not isinstance(settings.get("scheduler_paused"), bool):
            raise ValueError("scheduler_paused 必须是布尔值")
        if not isinstance(settings.get("node_probe_enabled"), bool):
            raise ValueError("node_probe_enabled 必须是布尔值")
        targets = settings.get("enabled_targets")
        if not isinstance(targets, list) or not targets:
            raise ValueError("enabled_targets 必须至少包含一个检测项")
        normalized = normalize_target_keys(targets, fallback_to_default=False)
        if len(normalized) != len(targets):
            raise ValueError("enabled_targets 包含无效或重复检测项")

    def create_admin(self, username: str, password_hash: str) -> None:
        now = iso_now()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO admins(username, password_hash, created_at, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(username) DO UPDATE SET "
                "password_hash=excluded.password_hash, updated_at=excluded.updated_at",
                (username, password_hash, now, now),
            )

    def cleanup_expired_sessions(self) -> None:
        self.execute("DELETE FROM sessions WHERE expires_at < ?", (iso_now(),))

    def record_check(
        self,
        task_id: str | None,
        node_id: int,
        result: dict[str, Any],
        next_check_at: str,
        _legacy_breaker_threshold: int | None = None,
    ) -> int:
        now = iso_now()
        with self.transaction() as connection:
            previous = connection.execute(
                "SELECT current_status, online_since, consecutive_failures,"
                "location_source "
                "FROM nodes WHERE id=?",
                (node_id,),
            ).fetchone()
            if not previous:
                raise RuntimeError("节点已不存在")
            status = result["status"]
            is_up = status in {"online", "degraded"}
            was_up = previous["current_status"] in {"online", "degraded"}
            is_unknown = status == "unknown"
            failures = (
                int(previous["consecutive_failures"])
                if is_unknown
                else 0
                if is_up
                else int(previous["consecutive_failures"]) + 1
            )
            online_since = previous["online_since"]
            recovery_at = None
            failure_at = None
            if is_up:
                if not was_up:
                    online_since = now
                    recovery_at = now
            elif not is_unknown:
                online_since = None
                failure_at = now
            run_values = (
                task_id,
                node_id,
                result["started_at"],
                result["finished_at"],
                status,
                result["health_score"],
                result.get("latency_avg_ms"),
                result.get("latency_p50_ms"),
                result.get("latency_p95_ms"),
                result.get("error_type"),
                result.get("attempt_count", 1),
                result.get("website_status"),
                result.get("website_health_score"),
                result.get("website_error_type"),
                result.get("node_probe_status"),
                result.get("node_latency_ms"),
                result.get("node_latency_p50_ms"),
                result.get("node_latency_p95_ms"),
                result.get("node_jitter_ms"),
                result.get("node_probe_successes"),
                result.get("node_probe_samples"),
                result.get("node_probe_http_code"),
                result.get("node_probe_target"),
                result.get("node_probe_error_type"),
                result.get("node_latency_method"),
                result.get("node_endpoint_status"),
                result.get("node_endpoint_successes"),
                result.get("node_endpoint_samples"),
                result.get("node_endpoint_latency_ms"),
                result.get("node_endpoint_latency_p50_ms"),
                result.get("node_endpoint_latency_p95_ms"),
                result.get("node_endpoint_jitter_ms"),
            )
            cursor = connection.execute(
                "INSERT INTO check_runs("
                "task_id,node_id,started_at,finished_at,status,health_score,"
                "latency_avg_ms,latency_p50_ms,latency_p95_ms,error_type,attempt_count,"
                "website_status,website_health_score,website_error_type,"
                "node_probe_status,node_latency_ms,node_latency_p50_ms,"
                "node_latency_p95_ms,node_jitter_ms,node_probe_successes,"
                "node_probe_samples,node_probe_http_code,node_probe_target,"
                "node_probe_error_type,node_latency_method,node_endpoint_status,"
                "node_endpoint_successes,node_endpoint_samples,"
                "node_endpoint_latency_ms,node_endpoint_latency_p50_ms,"
                "node_endpoint_latency_p95_ms,node_endpoint_jitter_ms"
                f") VALUES ({','.join('?' for _ in run_values)})",
                run_values,
            )
            run_id = int(cursor.lastrowid)
            for service in result["services"]:
                connection.execute(
                    "INSERT INTO service_results("
                    "check_run_id,service,status,reachable,dns_ok,tcp_ok,tls_ok,"
                    "http_code,latency_ms,dns_ms,tcp_ms,tls_ms,ttfb_ms,redirect_count,"
                    "final_host_class,feature_ok,error_type"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        service["service"],
                        service["status"],
                        int(service["reachable"]),
                        int(service["dns_ok"]),
                        int(service["tcp_ok"]),
                        int(service["tls_ok"]),
                        service.get("http_code"),
                        service.get("latency_ms"),
                        service.get("dns_ms"),
                        service.get("tcp_ms"),
                        service.get("tls_ms"),
                        service.get("ttfb_ms"),
                        service.get("redirect_count", 0),
                        service.get("final_host_class"),
                        int(service.get("feature_ok", False)),
                        service.get("error_type"),
                    ),
                )
            location = result.get("location")
            if isinstance(location, dict):
                detected_code = normalize_detected_country_code(
                    location.get("country_code")
                )
                provider_count = max(
                    0, min(3, int(location.get("provider_count") or 0))
                )
                if (
                    detected_code
                    and provider_count >= 2
                    and location.get("region_name")
                    and location.get("exit_ip_mask")
                ):
                    connection.execute(
                        "UPDATE nodes SET country_code=?,region_name=?,"
                        "location_source='auto',location_checked_at=?,"
                        "location_provider_count=?,exit_ip_mask=? WHERE id=?",
                        (
                            detected_code,
                            str(location["region_name"])[:120],
                            now,
                            provider_count,
                            str(location["exit_ip_mask"])[:80],
                            node_id,
                        ),
                    )
            elif (
                result.get("location_attempted")
                and previous["location_source"] != "manual"
            ):
                connection.execute(
                    "UPDATE nodes SET location_checked_at=?,"
                    "location_provider_count=0 WHERE id=?",
                    (now, node_id),
                )
            connection.execute(
                "UPDATE nodes SET current_status=?,health_score=?,last_latency_ms=?,"
                "last_website_latency_ms=?,last_node_jitter_ms=?,"
                "last_node_probe_status=?,last_node_probe_successes=?,"
                "last_node_probe_samples=?,last_node_probe_target=?,"
                "last_node_latency_method=?,last_node_endpoint_status=?,"
                "last_node_endpoint_successes=?,last_node_endpoint_samples=?,"
                "last_node_endpoint_latency_ms=?,"
                "last_node_endpoint_latency_p95_ms=?,"
                "last_node_endpoint_jitter_ms=?,"
                "online_since=?,last_checked_at=?,next_check_at=?,last_failure_at="
                "COALESCE(?,last_failure_at),last_recovery_at=COALESCE(?,last_recovery_at),"
                "consecutive_failures=?,circuit_open_until=?,last_error_type=?,updated_at=? "
                "WHERE id=?",
                (
                    status,
                    result["health_score"],
                    (
                        result.get("node_latency_ms")
                        if result.get("node_probe_status") is not None
                        else result.get("latency_avg_ms")
                    ),
                    result.get("latency_avg_ms"),
                    result.get("node_jitter_ms"),
                    result.get("node_probe_status"),
                    result.get("node_probe_successes"),
                    result.get("node_probe_samples"),
                    result.get("node_probe_target"),
                    result.get("node_latency_method"),
                    result.get("node_endpoint_status"),
                    result.get("node_endpoint_successes"),
                    result.get("node_endpoint_samples"),
                    result.get("node_endpoint_latency_ms"),
                    result.get("node_endpoint_latency_p95_ms"),
                    result.get("node_endpoint_jitter_ms"),
                    online_since,
                    now,
                    next_check_at,
                    failure_at,
                    recovery_at,
                    failures,
                    None,
                    result.get("error_type"),
                    now,
                    node_id,
                ),
            )
            if was_up and not is_up and not is_unknown:
                connection.execute(
                    "INSERT INTO events(node_id,event_type,severity,title,detail,created_at) "
                    "VALUES (?, 'failure', 'critical', '节点转为不可用', ?, ?)",
                    (node_id, result.get("error_type") or "检测未通过", now),
                )
            elif not was_up and is_up and previous["current_status"] not in {
                "pending",
                "unknown",
            }:
                connection.execute(
                    "UPDATE events SET recovered_at=? WHERE id=("
                    "SELECT id FROM events WHERE node_id=? AND event_type='failure' "
                    "AND recovered_at IS NULL ORDER BY created_at DESC LIMIT 1)",
                    (now, node_id),
                )
                connection.execute(
                    "INSERT INTO events(node_id,event_type,severity,title,detail,created_at) "
                    "VALUES (?, 'recovery', 'success', '节点已恢复', '手动或定时复测通过', ?)",
                    (node_id, now),
                )
        return run_id

    def record_observer_sample(
        self,
        status: str,
        interface: str | None,
        reason: str,
        sampled_at: str | None = None,
    ) -> None:
        if status not in {"online", "offline", "unknown"}:
            raise ValueError("无效的监测机链路状态")
        self.execute(
            "INSERT OR REPLACE INTO observer_samples("
            "sampled_at,status,interface,reason) VALUES (?,?,?,?)",
            (sampled_at or iso_now(), status, interface, reason[:80]),
        )

    def upsert_hourly_stats(self, older_than: str) -> int:
        rows = self.fetch_all(
            "SELECT cr.node_id,"
            "substr(cr.finished_at,1,13)||':00:00+00:00' AS bucket,"
            "cr.status,cr.health_score,cr.latency_avg_ms,"
            "cr.node_probe_status,cr.node_latency_ms,cr.node_jitter_ms,"
            "cr.attempt_count,COUNT(sr.id) AS service_samples,"
            "COALESCE(SUM(sr.reachable),0) AS service_reachable_samples "
            "FROM check_runs cr "
            "LEFT JOIN service_results sr ON sr.check_run_id=cr.id "
            "WHERE cr.finished_at < ? "
            "GROUP BY cr.id ORDER BY cr.node_id,bucket",
            (older_than,),
        )
        grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[(int(row["node_id"]), row["bucket"])].append(row)
        with self.transaction() as connection:
            for (node_id, bucket), samples in grouped.items():
                website_latencies = [
                    float(item["latency_avg_ms"])
                    for item in samples
                    if item["latency_avg_ms"] is not None
                ]
                node_samples = [
                    item for item in samples if item["node_probe_status"] is not None
                ]
                node_latencies = [
                    float(item["node_latency_ms"])
                    for item in node_samples
                    if item["node_latency_ms"] is not None
                ]
                node_jitters = [
                    float(item["node_jitter_ms"])
                    for item in node_samples
                    if item["node_jitter_ms"] is not None
                ]
                connection.execute(
                    "INSERT INTO hourly_stats("
                    "node_id,bucket_at,samples,online_samples,health_avg,"
                    "latency_avg_ms,latency_p50_ms,latency_p95_ms,"
                    "node_probe_samples,node_online_samples,node_health_avg,"
                    "node_latency_avg_ms,node_latency_p50_ms,node_latency_p95_ms,"
                    "service_samples,service_reachable_samples,retry_samples,"
                    "node_jitter_avg_ms,node_jitter_p95_ms"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(node_id,bucket_at) DO UPDATE SET "
                    "samples=excluded.samples,online_samples=excluded.online_samples,"
                    "health_avg=excluded.health_avg,latency_avg_ms=excluded.latency_avg_ms,"
                    "latency_p50_ms=excluded.latency_p50_ms,"
                    "latency_p95_ms=excluded.latency_p95_ms,"
                    "node_probe_samples=excluded.node_probe_samples,"
                    "node_online_samples=excluded.node_online_samples,"
                    "node_health_avg=excluded.node_health_avg,"
                    "node_latency_avg_ms=excluded.node_latency_avg_ms,"
                    "node_latency_p50_ms=excluded.node_latency_p50_ms,"
                    "node_latency_p95_ms=excluded.node_latency_p95_ms,"
                    "service_samples=excluded.service_samples,"
                    "service_reachable_samples=excluded.service_reachable_samples,"
                    "retry_samples=excluded.retry_samples,"
                    "node_jitter_avg_ms=excluded.node_jitter_avg_ms,"
                    "node_jitter_p95_ms=excluded.node_jitter_p95_ms",
                    (
                        node_id,
                        bucket,
                        len(samples),
                        sum(
                            item["status"] in {"online", "degraded"}
                            for item in samples
                        ),
                        statistics.fmean(
                            float(item["health_score"]) for item in samples
                        ),
                        (
                            statistics.fmean(website_latencies)
                            if website_latencies
                            else None
                        ),
                        (
                            statistics.median(website_latencies)
                            if website_latencies
                            else None
                        ),
                        percentile(website_latencies, 95),
                        len(node_samples),
                        sum(
                            item["status"] in {"online", "degraded"}
                            for item in node_samples
                        ),
                        (
                            statistics.fmean(
                                float(item["health_score"]) for item in node_samples
                            )
                            if node_samples
                            else None
                        ),
                        (
                            statistics.fmean(node_latencies)
                            if node_latencies
                            else None
                        ),
                        (
                            statistics.median(node_latencies)
                            if node_latencies
                            else None
                        ),
                        percentile(node_latencies, 95),
                        sum(int(item["service_samples"] or 0) for item in samples),
                        sum(
                            int(item["service_reachable_samples"] or 0)
                            for item in samples
                        ),
                        sum(int(item["attempt_count"] or 1) > 1 for item in samples),
                        (
                            statistics.fmean(node_jitters)
                            if node_jitters
                            else None
                        ),
                        percentile(node_jitters, 95),
                    ),
                )
        return len(grouped)

    def allocated_bytes(self) -> int:
        return sum(
            path.stat().st_size
            for path in (
                self.path,
                Path(f"{self.path}-wal"),
                Path(f"{self.path}-shm"),
            )
            if path.exists()
        )

    def maintenance(
        self,
        *,
        reason: str = "scheduled",
        aggressive: bool = False,
    ) -> dict[str, Any]:
        started = iso_now()
        before_bytes = self.allocated_bytes()
        settings = self.get_settings()
        raw_days = int(settings["raw_retention_days"])
        metrics_days = 7
        task_days = 30
        event_days = 365
        if aggressive:
            raw_days = min(raw_days, 7)
            metrics_days = 2
            task_days = 7
            event_days = 180
        raw_cutoff = (
            utc_now() - timedelta(days=raw_days)
        ).isoformat(timespec="seconds")
        hourly_cutoff = (
            utc_now() - timedelta(days=settings["hourly_retention_days"])
        ).isoformat(timespec="seconds")
        metrics_cutoff = (
            utc_now() - timedelta(days=metrics_days)
        ).isoformat(timespec="seconds")
        tasks_cutoff = (
            utc_now() - timedelta(days=task_days)
        ).isoformat(timespec="seconds")
        events_cutoff = (
            utc_now() - timedelta(days=event_days)
        ).isoformat(timespec="seconds")
        self.upsert_hourly_stats(raw_cutoff)
        with self.transaction() as connection:
            deleted_runs = connection.execute(
                "DELETE FROM check_runs WHERE finished_at < ?", (raw_cutoff,)
            ).rowcount
            connection.execute(
                "DELETE FROM hourly_stats WHERE bucket_at < ?", (hourly_cutoff,)
            )
            deleted_observer_samples = connection.execute(
                "DELETE FROM observer_samples WHERE sampled_at < ?",
                (hourly_cutoff,),
            ).rowcount
            deleted_metrics = connection.execute(
                "DELETE FROM system_metrics WHERE sampled_at < ?", (metrics_cutoff,)
            ).rowcount
            deleted_tasks = connection.execute(
                "DELETE FROM tasks WHERE created_at < ?", (tasks_cutoff,)
            ).rowcount
            deleted_events = connection.execute(
                "DELETE FROM events WHERE created_at < ? "
                "AND (recovered_at IS NOT NULL OR event_type NOT IN ('failure'))",
                (events_cutoff,),
            ).rowcount
            connection.execute(
                "DELETE FROM sessions WHERE expires_at < ?", (iso_now(),)
            )
            connection.execute("PRAGMA incremental_vacuum(200)")
        after_bytes = self.allocated_bytes()
        result = {
            "reason": reason,
            "status": "completed",
            "started_at": started,
            "finished_at": iso_now(),
            "before_bytes": before_bytes,
            "after_bytes": after_bytes,
            "freed_bytes": max(0, before_bytes - after_bytes),
            "deleted_runs": int(deleted_runs),
            "deleted_metrics": int(deleted_metrics),
            "deleted_tasks": int(deleted_tasks),
            "deleted_events": int(deleted_events),
            "deleted_observer_samples": int(deleted_observer_samples),
            "aggressive": aggressive,
        }
        self.execute(
            "INSERT INTO maintenance_runs("
            "reason,status,started_at,finished_at,before_bytes,after_bytes,"
            "freed_bytes,deleted_runs,deleted_metrics,deleted_tasks,deleted_events,detail"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                reason,
                "completed",
                started,
                result["finished_at"],
                before_bytes,
                after_bytes,
                result["freed_bytes"],
                result["deleted_runs"],
                result["deleted_metrics"],
                result["deleted_tasks"],
                result["deleted_events"],
                json.dumps(
                    {
                        "aggressive": aggressive,
                        "deleted_observer_samples": int(
                            deleted_observer_samples
                        ),
                    },
                    separators=(",", ":"),
                ),
            ),
        )
        self.execute(
            "DELETE FROM maintenance_runs WHERE id NOT IN "
            "(SELECT id FROM maintenance_runs ORDER BY finished_at DESC LIMIT 100)"
        )
        return result

    def safe_export_csv(self) -> bytes:
        rows = self.fetch_all(
            "SELECT n.name,n.protocol,n.endpoint_mask,n.current_status,n.health_score,"
            "n.last_latency_ms,n.last_website_latency_ms,n.last_node_latency_method,"
            "n.online_since,"
            "n.last_checked_at,n.consecutive_failures,"
            "n.last_error_type,n.country_code,n.region_name,n.location_source,"
            "n.exit_ip_mask,s.name AS subscription_name "
            "FROM nodes n JOIN subscriptions s ON s.id=n.subscription_id "
            "ORDER BY n.health_score DESC,n.name"
        )
        buffer = io.StringIO()
        fields = [
            "节点",
            "协议",
            "脱敏端点",
            "状态",
            "健康度",
            "本地连接节点延迟毫秒",
            "经节点访问网站平均耗时毫秒",
            "本地连接节点测速方式",
            "连续在线起点",
            "最近检测",
            "连续失败",
            "错误类型",
            "出口国家代码",
            "出口国家或地区",
            "地区识别方式",
            "出口 IP（脱敏）",
            "订阅",
        ]
        writer = csv.writer(buffer)
        writer.writerow(fields)
        for row in rows:
            writer.writerow(
                [
                    _safe_csv_cell(value)
                    for value in (
                    row["name"],
                    row["protocol"],
                    row["endpoint_mask"],
                    row["current_status"],
                    row["health_score"],
                    row["last_latency_ms"],
                    row["last_website_latency_ms"],
                    row["last_node_latency_method"],
                    row["online_since"],
                    row["last_checked_at"],
                    row["consecutive_failures"],
                    row["last_error_type"],
                    row["country_code"],
                    row["region_name"],
                    row["location_source"],
                    row["exit_ip_mask"],
                    row["subscription_name"],
                    )
                ]
            )
        return ("\ufeff" + buffer.getvalue()).encode("utf-8")

    def online_backup(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as source, sqlite3.connect(destination) as target:
            source.backup(target)


def percentile(values: Sequence[float], percentile_value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile_value / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
