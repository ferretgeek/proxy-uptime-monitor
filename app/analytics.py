from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from .database import Database, iso_now, parse_time, utc_now
from .locations import country_options
from .storage import StorageManager
from .targets import normalize_target_keys


NODE_LEVELS = {
    "online": "healthy",
    "degraded": "warning",
    "offline": "critical",
    "removed": "critical",
    "pending": "unknown",
    "unknown": "unknown",
}

SERVICE_LEVELS = {
    "available": "healthy",
    "login_required": "warning",
    "region_blocked": "warning",
    "service_blocked": "warning",
    "service_error": "warning",
    "response_error": "warning",
    "content_mismatch": "unknown",
    "uncertain": "unknown",
    "timeout": "critical",
    "dns_error": "critical",
    "tcp_error": "critical",
    "tls_error": "critical",
    "proxy_error": "critical",
    "proxy_configuration": "critical",
}

LATENCY_WINDOWS = (
    ("12h", 12, "12 小时"),
    ("24h", 24, "24 小时"),
    ("72h", 72, "72 小时"),
    ("168h", 168, "7 天"),
    ("360h", 360, "15 天"),
    ("720h", 720, "30 天"),
)


def _enabled_target_keys(database: Database) -> tuple[str, ...]:
    return normalize_target_keys(database.get_settings().get("enabled_targets"))


def _merge_observer_intervals(
    intervals: list[tuple[datetime, datetime, str]],
) -> list[tuple[datetime, datetime, str]]:
    merged: list[tuple[datetime, datetime, str]] = []
    for start, end, status in sorted(intervals, key=lambda item: item[0]):
        if end <= start:
            continue
        if (
            merged
            and merged[-1][2] == status
            and start <= merged[-1][1] + timedelta(seconds=1)
        ):
            previous = merged[-1]
            merged[-1] = (previous[0], max(previous[1], end), status)
        else:
            merged.append((start, end, status))
    return merged


def _observer_intervals(
    database: Database,
    start: datetime,
    end: datetime,
    *,
    check_interval_minutes: int,
    jitter_seconds: int,
) -> list[tuple[datetime, datetime, str]]:
    previous = database.fetch_one(
        "SELECT sampled_at,status,reason FROM observer_samples "
        "WHERE sampled_at<? ORDER BY sampled_at DESC LIMIT 1",
        (start.isoformat(timespec="seconds"),),
    )
    rows = database.fetch_all(
        "SELECT sampled_at,status,reason FROM observer_samples "
        "WHERE sampled_at>=? AND sampled_at<=? ORDER BY sampled_at",
        (
            start.isoformat(timespec="seconds"),
            end.isoformat(timespec="seconds"),
        ),
    )
    if previous:
        rows.insert(0, previous)
    if not rows:
        # Fresh test databases and installations predating observer sampling
        # still have useful node history. Treat it as legacy observable data;
        # production migrations backfill explicit activity samples.
        return [(start, end, "online")]
    samples: list[tuple[datetime, str, str]] = []
    for row in rows:
        sampled_at = parse_time(row["sampled_at"])
        if sampled_at:
            samples.append(
                (sampled_at, str(row["status"]), str(row["reason"] or ""))
            )
    intervals: list[tuple[datetime, datetime, str]] = []
    for index, (sampled_at, status, reason) in enumerate(samples):
        if reason == "legacy_check_activity":
            ttl_seconds = (
                max(5, check_interval_minutes) * 120
                + max(0, jitter_seconds)
                + 120
            )
        else:
            ttl_seconds = 180
        expires_at = sampled_at + timedelta(seconds=ttl_seconds)
        next_at = samples[index + 1][0] if index + 1 < len(samples) else end
        segment_start = max(start, sampled_at)
        segment_end = min(end, expires_at, next_at)
        if segment_end > segment_start:
            intervals.append((segment_start, segment_end, status))
    return _merge_observer_intervals(intervals)


def _overlap_seconds(
    segments: list[tuple[datetime, datetime, float]],
    observer_online: list[tuple[datetime, datetime]],
) -> tuple[float, float]:
    known_seconds = 0.0
    online_seconds = 0.0
    observer_index = 0
    for start, end, value in segments:
        while (
            observer_index < len(observer_online)
            and observer_online[observer_index][1] <= start
        ):
            observer_index += 1
        index = observer_index
        while index < len(observer_online):
            online_start, online_end = observer_online[index]
            if online_start >= end:
                break
            overlap = (
                min(end, online_end) - max(start, online_start)
            ).total_seconds()
            if overlap > 0:
                known_seconds += overlap
                online_seconds += overlap * value
            index += 1
    return known_seconds, online_seconds


def _time_reliability(
    database: Database,
    node_ids: Iterable[int],
    *,
    start: datetime,
    end: datetime,
) -> dict[int, dict[str, Any]]:
    ids = list(dict.fromkeys(int(value) for value in node_ids))
    if not ids:
        return {}
    settings = database.get_settings()
    check_minutes = int(settings["check_interval_minutes"])
    offline_minutes = int(settings["offline_check_interval_minutes"])
    jitter_seconds = int(settings["jitter_seconds"])
    observer = _observer_intervals(
        database,
        start,
        end,
        check_interval_minutes=check_minutes,
        jitter_seconds=jitter_seconds,
    )
    observer_online = [
        (segment_start, segment_end)
        for segment_start, segment_end, status in observer
        if status == "online"
    ]
    observer_online_seconds = sum(
        (segment_end - segment_start).total_seconds()
        for segment_start, segment_end in observer_online
    )
    observer_offline_seconds = sum(
        (segment_end - segment_start).total_seconds()
        for segment_start, segment_end, status in observer
        if status == "offline"
    )
    total_seconds = max(1.0, (end - start).total_seconds())
    longest_interval = max(check_minutes, offline_minutes)
    lookback = start - timedelta(
        minutes=longest_interval * 3,
        seconds=jitter_seconds * 3,
    )
    placeholders = ",".join("?" for _ in ids)
    raw_rows = database.fetch_all(
        "SELECT node_id,finished_at,status,node_probe_successes,"
        "node_probe_samples,node_probe_status FROM check_runs "
        f"WHERE node_id IN ({placeholders}) AND finished_at>=? "
        "AND finished_at<=? ORDER BY node_id,finished_at",
        tuple(ids)
        + (
            lookback.isoformat(timespec="seconds"),
            end.isoformat(timespec="seconds"),
        ),
    )
    hourly_rows = database.fetch_all(
        "SELECT node_id,bucket_at,node_probe_samples,node_online_samples "
        "FROM hourly_stats "
        f"WHERE node_id IN ({placeholders}) AND bucket_at>=? "
        "AND bucket_at<=? AND node_probe_samples>0 "
        "ORDER BY node_id,bucket_at",
        tuple(ids)
        + (
            start.isoformat(timespec="seconds"),
            end.isoformat(timespec="seconds"),
        ),
    )
    raw_by_node: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in raw_rows:
        raw_by_node[int(row["node_id"])].append(row)
    hourly_by_node: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in hourly_rows:
        hourly_by_node[int(row["node_id"])].append(row)
    result: dict[int, dict[str, Any]] = {}
    for node_id in ids:
        node_raw = raw_by_node.get(node_id, [])
        parsed_raw = [
            (parse_time(row["finished_at"]), row)
            for row in node_raw
        ]
        parsed_raw = [
            (sampled_at, row)
            for sampled_at, row in parsed_raw
            if sampled_at is not None
        ]
        first_raw_at = (
            max(start, parsed_raw[0][0])
            if parsed_raw
            else end
        )
        segments: list[tuple[datetime, datetime, float]] = []
        hourly_samples = 0
        for row in hourly_by_node.get(node_id, []):
            bucket = parse_time(row["bucket_at"])
            if bucket is None or bucket >= first_raw_at:
                continue
            bucket_end = min(end, bucket + timedelta(hours=1), first_raw_at)
            bucket_start = max(start, bucket)
            samples = int(row["node_probe_samples"] or 0)
            if bucket_end <= bucket_start or samples <= 0:
                continue
            value = max(
                0.0,
                min(
                    1.0,
                    int(row["node_online_samples"] or 0) / samples,
                ),
            )
            segments.append((bucket_start, bucket_end, value))
            hourly_samples += samples
        for index, (sampled_at, row) in enumerate(parsed_raw):
            status = str(row["status"])
            interval_minutes = (
                offline_minutes if status == "offline" else check_minutes
            )
            expires_at = sampled_at + timedelta(
                minutes=interval_minutes * 3,
                seconds=jitter_seconds * 3,
            )
            next_at = (
                parsed_raw[index + 1][0]
                if index + 1 < len(parsed_raw)
                else end
            )
            segment_start = max(start, sampled_at)
            segment_end = min(end, expires_at, next_at)
            if segment_end <= segment_start:
                continue
            if status == "online":
                value = 1.0
            elif status == "degraded":
                successes = int(row["node_probe_successes"] or 0)
                samples = int(row["node_probe_samples"] or 0)
                value = successes / samples if samples else 0.5
            elif status == "offline":
                value = 0.0
            else:
                continue
            segments.append((segment_start, segment_end, value))
        segments.sort(key=lambda item: item[0])
        known_seconds, online_seconds = _overlap_seconds(
            segments,
            observer_online,
        )
        window_raw = [
            row
            for sampled_at, row in parsed_raw
            if sampled_at >= start
            and row["node_probe_status"] is not None
        ]
        samples = len(window_raw) + hourly_samples
        if known_seconds > 0:
            availability = round(100.0 * online_seconds / known_seconds, 2)
        elif window_raw:
            availability = round(
                100.0
                * sum(
                    row["status"] in {"online", "degraded"}
                    for row in window_raw
                )
                / len(window_raw),
                2,
            )
        else:
            availability = None
        coverage = round(100.0 * known_seconds / total_seconds, 2)
        if coverage >= 90.0 and samples >= 12:
            confidence = "high"
        elif coverage >= 60.0 and samples >= 4:
            confidence = "medium"
        elif samples:
            confidence = "low"
        else:
            confidence = "none"
        result[node_id] = {
            "availability": availability,
            "availability_samples": samples,
            "availability_observed_seconds": round(known_seconds),
            "coverage_percent": coverage,
            "confidence": confidence,
            "observer_online_seconds": round(observer_online_seconds),
            "observer_offline_seconds": round(observer_offline_seconds),
            "unknown_seconds": round(
                max(
                    0.0,
                    total_seconds
                    - observer_online_seconds
                    - observer_offline_seconds,
                )
            ),
        }
    return result


def _availability_maps(
    database: Database,
    node_ids: Iterable[int] | None = None,
) -> dict[int, dict[str, float | None]]:
    ids = list(dict.fromkeys(int(value) for value in (node_ids or [])))
    if not ids:
        rows = database.fetch_all(
            "SELECT id FROM nodes WHERE source_present=1"
        )
        ids = [int(row["id"]) for row in rows]
    current = utc_now()
    result: dict[int, dict[str, float | None]] = {
        node_id: {} for node_id in ids
    }
    for key, delta in (
        ("24h", timedelta(days=1)),
        ("7d", timedelta(days=7)),
        ("30d", timedelta(days=30)),
    ):
        reliability = _time_reliability(
            database,
            ids,
            start=current - delta,
            end=current,
        )
        for node_id in ids:
            result[node_id][key] = reliability.get(node_id, {}).get(
                "availability"
            )
    return result


def _latest_services(
    database: Database,
    node_ids: Iterable[int] | None = None,
) -> dict[int, dict[str, dict[str, Any]]]:
    target_keys = _enabled_target_keys(database)
    if not target_keys:
        return {}
    ids = list(dict.fromkeys(int(value) for value in (node_ids or [])))
    filters = []
    params: list[Any] = []
    if ids:
        placeholders = ",".join("?" for _ in ids)
        filters.append(f"cr.node_id IN ({placeholders})")
        params.extend(ids)
    service_placeholders = ",".join("?" for _ in target_keys)
    filters.append(f"sr.service IN ({service_placeholders})")
    params.extend(target_keys)
    where = " AND ".join(filters)
    rows = database.fetch_all(
        "WITH latest AS ("
        " SELECT node_id,MAX(id) AS run_id FROM check_runs GROUP BY node_id"
        ") SELECT cr.node_id,sr.service,sr.status,sr.reachable,sr.latency_ms,"
        "sr.http_code,sr.error_type,sr.dns_ok,sr.tcp_ok,sr.tls_ok,"
        "sr.redirect_count,sr.final_host_class,sr.feature_ok "
        "FROM latest JOIN check_runs cr ON cr.id=latest.run_id "
        "JOIN nodes n ON n.id=cr.node_id AND n.source_present=1 "
        "JOIN service_results sr ON sr.check_run_id=cr.id "
        f"WHERE {where}",
        tuple(params),
    )
    result: dict[int, dict[str, dict[str, Any]]] = {}
    for row in rows:
        status = "available" if row["status"] == "captcha" else row["status"]
        result.setdefault(int(row["node_id"]), {})[row["service"]] = {
            "status": status,
            "level": SERVICE_LEVELS.get(status, "unknown"),
            "reachable": bool(row["reachable"]),
            "latency_ms": row["latency_ms"],
            "http_code": row["http_code"],
            "error_type": None if row["error_type"] == "captcha" else row["error_type"],
            "dns_ok": bool(row["dns_ok"]),
            "tcp_ok": bool(row["tcp_ok"]),
            "tls_ok": bool(row["tls_ok"]),
            "redirect_count": int(row["redirect_count"]),
            "final_host_class": row["final_host_class"],
            "feature_ok": bool(row["feature_ok"]),
        }
    return result


def _decorate_nodes(database: Database, nodes: list[dict[str, Any]]) -> None:
    ids = [int(node["id"]) for node in nodes]
    rates = _availability_maps(database, ids)
    services = _latest_services(database, ids)
    targets = _enabled_target_keys(database)
    node_probe_enabled = bool(
        database.get_settings().get("node_probe_enabled", True)
    )
    for node in nodes:
        node_id = int(node["id"])
        node["enabled"] = bool(node["enabled"])
        node["source_present"] = bool(node["source_present"])
        # A paused node has no current monitoring verdict.  Keep the API's
        # semantic level aligned with the gray "已停用" state rendered by the
        # console instead of leaking a stale pre-pause failure as critical.
        node["level"] = (
            NODE_LEVELS.get(node["current_status"], "unknown")
            if node["enabled"]
            else "unknown"
        )
        node["availability_24h"] = rates.get(node_id, {}).get("24h")
        node["availability_7d"] = rates.get(node_id, {}).get("7d")
        node["availability_30d"] = rates.get(node_id, {}).get("30d")
        node["services"] = services.get(node_id, {})
        node["active_tests"] = list(targets)
        node["node_probe_enabled"] = node_probe_enabled


def list_nodes(database: Database) -> list[dict[str, Any]]:
    rows = database.fetch_all(
        "SELECT n.id,n.name,n.protocol,n.endpoint_mask,n.enabled,n.source_present,"
        "n.current_status,n.health_score,n.last_latency_ms,"
        "n.last_website_latency_ms,n.last_node_jitter_ms,"
        "n.last_node_probe_status,n.last_node_probe_successes,"
        "n.last_node_probe_samples,n.last_node_probe_target,"
        "n.last_node_latency_method,n.last_node_endpoint_status,"
        "n.last_node_endpoint_successes,n.last_node_endpoint_samples,"
        "n.last_node_endpoint_latency_ms,n.last_node_endpoint_latency_p95_ms,"
        "n.last_node_endpoint_jitter_ms,n.online_since,"
        "n.last_checked_at,n.next_check_at,n.last_failure_at,n.last_recovery_at,"
        "n.consecutive_failures,n.circuit_open_until,n.last_error_type,"
        "n.country_code,n.region_name,n.location_source,n.location_checked_at,"
        "n.location_provider_count,n.exit_ip_mask,"
        "s.id AS subscription_id,s.name AS subscription_name "
        "FROM nodes n JOIN subscriptions s ON s.id=n.subscription_id "
        "WHERE n.source_present=1 ORDER BY "
        "CASE WHEN n.enabled=0 THEN 5 ELSE CASE n.current_status "
        "WHEN 'offline' THEN 0 WHEN 'degraded' THEN 1 "
        "WHEN 'unknown' THEN 2 WHEN 'pending' THEN 3 ELSE 4 END END,"
        "n.health_score,n.id"
    )
    _decorate_nodes(database, rows)
    return rows


def node_page(
    database: Database,
    *,
    page: int = 1,
    page_size: int = 30,
    search: str = "",
    status: str = "",
    country: str = "",
    service: str = "",
    sort: str = "status",
    direction: str = "asc",
    enabled_only: bool = False,
) -> dict[str, Any]:
    page = max(1, page)
    page_size = max(10, min(page_size, 100))
    conditions = ["n.source_present=1"]
    params: list[Any] = []
    if enabled_only:
        conditions.append("n.enabled=1")
    search = search.strip()
    if search:
        conditions.append(
            "(n.name LIKE ? ESCAPE '\\' OR n.protocol LIKE ? ESCAPE '\\' "
            "OR s.name LIKE ? ESCAPE '\\' OR n.region_name LIKE ? ESCAPE '\\')"
        )
        escaped = (
            search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        params.extend([f"%{escaped}%"] * 4)
    valid_statuses = {"online", "degraded", "offline", "pending", "unknown"}
    if status == "paused":
        conditions.append("n.enabled=0")
    elif status in valid_statuses:
        conditions.append("n.enabled=1 AND n.current_status=?")
        params.append(status)
    if country:
        conditions.append("n.country_code=?")
        params.append(country.upper())
    targets = _enabled_target_keys(database)
    if service in targets:
        conditions.append(
            "EXISTS (SELECT 1 FROM service_results sr "
            "WHERE sr.check_run_id=(SELECT MAX(cr.id) FROM check_runs cr "
            "WHERE cr.node_id=n.id) AND sr.service=?)"
        )
        params.append(service)
    where = " AND ".join(conditions)
    count = database.fetch_one(
        "SELECT COUNT(*) AS total FROM nodes n "
        "JOIN subscriptions s ON s.id=n.subscription_id "
        f"WHERE {where}",
        tuple(params),
    )
    total = int(count["total"] if count else 0)
    pages = max(1, math.ceil(total / page_size))
    page = min(page, pages)
    sort_map = {
        "status": (
            "CASE WHEN n.enabled=0 THEN 5 ELSE CASE n.current_status WHEN 'offline' THEN 0 "
            "WHEN 'degraded' THEN 1 WHEN 'unknown' THEN 2 "
            "WHEN 'pending' THEN 3 ELSE 4 END END"
        ),
        "name": "n.name COLLATE NOCASE",
        "health": "n.health_score",
        "checked": "COALESCE(n.last_checked_at,'')",
        "country": "n.region_name COLLATE NOCASE",
    }
    order_direction = "DESC" if direction.lower() == "desc" else "ASC"
    latency_sort_map = {
        "latency": "n.last_latency_ms",
        "node_latency": "n.last_latency_ms",
        "website_latency": "n.last_website_latency_ms",
    }
    if sort in latency_sort_map:
        latency_column = latency_sort_map[sort]
        order_clause = (
            f"{latency_column} IS NULL ASC,{latency_column} {order_direction}"
        )
    else:
        order = sort_map.get(sort, sort_map["status"])
        order_clause = f"{order} {order_direction}"
    rows = database.fetch_all(
        "SELECT n.id,n.name,n.protocol,n.endpoint_mask,n.enabled,n.source_present,"
        "n.current_status,n.health_score,n.last_latency_ms,"
        "n.last_website_latency_ms,n.last_node_jitter_ms,"
        "n.last_node_probe_status,n.last_node_probe_successes,"
        "n.last_node_probe_samples,n.last_node_probe_target,"
        "n.last_node_latency_method,n.last_node_endpoint_status,"
        "n.last_node_endpoint_successes,n.last_node_endpoint_samples,"
        "n.last_node_endpoint_latency_ms,n.last_node_endpoint_latency_p95_ms,"
        "n.last_node_endpoint_jitter_ms,n.online_since,"
        "n.last_checked_at,n.next_check_at,n.last_failure_at,n.last_recovery_at,"
        "n.consecutive_failures,n.circuit_open_until,n.last_error_type,"
        "n.country_code,n.region_name,n.location_source,n.location_checked_at,"
        "n.location_provider_count,n.exit_ip_mask,"
        "s.id AS subscription_id,s.name AS subscription_name "
        "FROM nodes n JOIN subscriptions s ON s.id=n.subscription_id "
        f"WHERE {where} ORDER BY {order_clause},n.id ASC LIMIT ? OFFSET ?",
        tuple(params + [page_size, (page - 1) * page_size]),
    )
    _decorate_nodes(database, rows)
    facet_where = "source_present=1"
    if enabled_only:
        facet_where += " AND enabled=1"
    status_rows = database.fetch_all(
        "SELECT CASE WHEN enabled=0 THEN 'paused' ELSE current_status END AS value,"
        f"COUNT(*) AS count FROM nodes WHERE {facet_where} GROUP BY value"
    )
    country_rows = database.fetch_all(
        f"SELECT country_code,COUNT(*) AS count FROM nodes WHERE {facet_where} "
        "GROUP BY country_code"
    )
    return {
        "items": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "facets": {
            "statuses": {
                row["value"]: int(row["count"]) for row in status_rows
            },
            "countries": [
                {
                    **item,
                    "count": next(
                        (
                            int(row["count"])
                            for row in country_rows
                            if row["country_code"] == item["code"]
                        ),
                        0,
                    ),
                }
                for item in country_options(
                    row["country_code"] for row in country_rows
                )
            ],
        },
    }


def _latency_quality_score(
    value: float | None,
    *,
    good: float,
    acceptable: float,
    maximum: float,
) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    value = max(0.0, float(value))
    if value <= good:
        return 100.0
    if value <= acceptable:
        return 100.0 - 30.0 * (value - good) / (acceptable - good)
    if value <= maximum:
        return 70.0 - 70.0 * (value - acceptable) / (maximum - acceptable)
    return 0.0


def _weighted_percentile(
    values: Iterable[tuple[float | None, int]],
    percentile_value: float,
) -> float | None:
    available = sorted(
        (
            float(value),
            max(1, int(weight)),
        )
        for value, weight in values
        if value is not None and math.isfinite(float(value)) and int(weight) > 0
    )
    if not available:
        return None
    target = max(0.0, min(1.0, percentile_value / 100.0)) * sum(
        weight for _, weight in available
    )
    cumulative = 0
    for value, weight in available:
        cumulative += weight
        if cumulative >= target:
            return round(value, 2)
    return round(available[-1][0], 2)


def _quality_windows(
    database: Database,
    node_ids: list[int],
    *,
    current: datetime,
    cutoffs: dict[str, str],
) -> dict[int, dict[str, dict[str, float | int | None]]]:
    if not node_ids:
        return {}
    placeholders = ",".join("?" for _ in node_ids)
    raw_rows = database.fetch_all(
        "SELECT node_id,finished_at,node_latency_ms,node_latency_p95_ms,"
        "latency_avg_ms,latency_p95_ms,node_jitter_ms,attempt_count "
        "FROM check_runs "
        f"WHERE node_id IN ({placeholders}) AND finished_at>=? "
        "ORDER BY node_id,finished_at",
        tuple(node_ids) + (cutoffs["720h"],),
    )
    service_rows = database.fetch_all(
        "SELECT cr.node_id,cr.finished_at,COUNT(sr.id) AS samples,"
        "COALESCE(SUM(sr.reachable),0) AS reachable "
        "FROM check_runs cr "
        "JOIN service_results sr ON sr.check_run_id=cr.id "
        f"WHERE cr.node_id IN ({placeholders}) AND cr.finished_at>=? "
        "GROUP BY cr.id ORDER BY cr.node_id,cr.finished_at",
        tuple(node_ids) + (cutoffs["720h"],),
    )
    hourly_rows = database.fetch_all(
        "SELECT node_id,bucket_at,samples,node_probe_samples,"
        "node_latency_p95_ms,latency_p95_ms,service_samples,"
        "service_reachable_samples,retry_samples,node_jitter_p95_ms "
        "FROM hourly_stats "
        f"WHERE node_id IN ({placeholders}) AND bucket_at>=? "
        "ORDER BY node_id,bucket_at",
        tuple(node_ids) + (cutoffs["720h"],),
    )
    raw_by_node: dict[int, list[dict[str, Any]]] = defaultdict(list)
    service_by_node: dict[int, list[dict[str, Any]]] = defaultdict(list)
    hourly_by_node: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in raw_rows:
        raw_by_node[int(row["node_id"])].append(row)
    for row in service_rows:
        service_by_node[int(row["node_id"])].append(row)
    for row in hourly_rows:
        hourly_by_node[int(row["node_id"])].append(row)
    result: dict[int, dict[str, dict[str, float | int | None]]] = defaultdict(dict)
    for node_id in node_ids:
        for key, _hours, _label in LATENCY_WINDOWS:
            cutoff = parse_time(cutoffs[key])
            if cutoff is None:
                raise RuntimeError(f"内部时间窗口无效：{key}")
            node_tail: list[tuple[float | None, int]] = []
            website_tail: list[tuple[float | None, int]] = []
            jitter_tail: list[tuple[float | None, int]] = []
            retries = 0
            checks = 0
            service_samples = 0
            service_reachable = 0
            for row in raw_by_node.get(node_id, []):
                sampled_at = parse_time(row["finished_at"])
                if sampled_at is None or sampled_at < cutoff:
                    continue
                node_tail.append(
                    (
                        row["node_latency_p95_ms"]
                        if row["node_latency_p95_ms"] is not None
                        else row["node_latency_ms"],
                        1,
                    )
                )
                website_tail.append(
                    (
                        row["latency_p95_ms"]
                        if row["latency_p95_ms"] is not None
                        else row["latency_avg_ms"],
                        1,
                    )
                )
                jitter_tail.append((row["node_jitter_ms"], 1))
                checks += 1
                retries += int(row["attempt_count"] or 1) > 1
            for row in service_by_node.get(node_id, []):
                sampled_at = parse_time(row["finished_at"])
                if sampled_at is None or sampled_at < cutoff:
                    continue
                service_samples += int(row["samples"] or 0)
                service_reachable += int(row["reachable"] or 0)
            for row in hourly_by_node.get(node_id, []):
                sampled_at = parse_time(row["bucket_at"])
                if sampled_at is None or sampled_at < cutoff:
                    continue
                node_weight = int(row["node_probe_samples"] or 0)
                sample_weight = int(row["samples"] or 0)
                node_tail.append((row["node_latency_p95_ms"], node_weight))
                website_tail.append((row["latency_p95_ms"], sample_weight))
                jitter_tail.append((row["node_jitter_p95_ms"], node_weight))
                checks += sample_weight
                retries += int(row["retry_samples"] or 0)
                service_samples += int(row["service_samples"] or 0)
                service_reachable += int(
                    row["service_reachable_samples"] or 0
                )
            result[node_id][key] = {
                "node_latency_p95_ms": _weighted_percentile(node_tail, 95),
                "website_latency_p95_ms": _weighted_percentile(
                    website_tail,
                    95,
                ),
                "node_jitter_p95_ms": _weighted_percentile(jitter_tail, 95),
                "website_availability": (
                    round(100.0 * service_reachable / service_samples, 2)
                    if service_samples
                    else None
                ),
                "website_samples": service_samples,
                "retry_rate": (
                    round(100.0 * retries / checks, 2)
                    if checks
                    else None
                ),
                "retry_samples": checks,
            }
    return result


def _retry_quality_score(value: float | None) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    value = max(0.0, float(value))
    if value <= 1.0:
        return 100.0
    if value <= 5.0:
        return 100.0 - 30.0 * (value - 1.0) / 4.0
    if value <= 20.0:
        return 70.0 - 70.0 * (value - 5.0) / 15.0
    return 0.0


def _period_score(
    availability: float | None,
    node_latency_ms: float | None,
    website_latency_ms: float | None,
    *,
    website_availability: float | None = None,
    node_jitter_ms: float | None = None,
    retry_rate: float | None = None,
) -> float | None:
    if availability is None or not math.isfinite(float(availability)):
        return None
    availability_score = max(0.0, min(100.0, float(availability)))
    website_availability_score = (
        max(0.0, min(100.0, float(website_availability)))
        if website_availability is not None
        and math.isfinite(float(website_availability))
        else 0.0
    )
    node_quality = _latency_quality_score(
        node_latency_ms,
        good=600.0,
        acceptable=1500.0,
        maximum=4000.0,
    )
    website_quality = _latency_quality_score(
        website_latency_ms,
        good=1800.0,
        acceptable=3500.0,
        maximum=8000.0,
    )
    jitter_quality = _latency_quality_score(
        node_jitter_ms,
        good=80.0,
        acceptable=250.0,
        maximum=800.0,
    )
    retry_quality = _retry_quality_score(retry_rate)
    stability_parts = [
        (jitter_quality, 0.70),
        (retry_quality, 0.30),
    ]
    stability_present = [
        (float(value), weight)
        for value, weight in stability_parts
        if value is not None
    ]
    stability_quality = (
        sum(value * weight for value, weight in stability_present)
        / sum(weight for _, weight in stability_present)
        if stability_present
        else 0.0
    )
    return round(
        availability_score * 0.45
        + website_availability_score * 0.20
        + float(node_quality or 0.0) * 0.15
        + float(website_quality or 0.0) * 0.10
        + stability_quality * 0.10,
        1,
    )


def _score_level(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 90:
        return "healthy"
    if value >= 70:
        return "warning"
    return "critical"


def latency_summary(
    database: Database,
    *,
    page: int = 1,
    page_size: int = 30,
    search: str = "",
    country: str = "",
    sort: str = "score",
    direction: str = "desc",
    enabled_only: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate six bounded periods without returning raw historical samples."""

    page = max(1, page)
    page_size = max(10, min(page_size, 100))
    conditions = ["n.source_present=1"]
    params: list[Any] = []
    if enabled_only:
        conditions.append("n.enabled=1")
    search = search.strip()
    if search:
        escaped = (
            search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        conditions.append(
            "(n.name LIKE ? ESCAPE '\\' OR n.protocol LIKE ? ESCAPE '\\' "
            "OR s.name LIKE ? ESCAPE '\\' OR n.region_name LIKE ? ESCAPE '\\')"
        )
        params.extend([f"%{escaped}%"] * 4)
    if country:
        conditions.append("n.country_code=?")
        params.append(country.upper())
    rows = database.fetch_all(
        "SELECT n.id,n.name,n.protocol,n.country_code,n.region_name,"
        "n.last_checked_at,s.name AS subscription_name "
        "FROM nodes n JOIN subscriptions s ON s.id=n.subscription_id "
        f"WHERE {' AND '.join(conditions)}",
        tuple(params),
    )

    current = now or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    else:
        current = current.astimezone(UTC)
    cutoffs = {
        key: (current - timedelta(hours=hours)).isoformat(timespec="seconds")
        for key, hours, _ in LATENCY_WINDOWS
    }
    by_node: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    node_ids = [int(row["id"]) for row in rows]
    reliability_by_window = {
        key: _time_reliability(
            database,
            node_ids,
            start=current - timedelta(hours=hours),
            end=current,
        )
        for key, hours, _label in LATENCY_WINDOWS
    }
    quality_by_node = _quality_windows(
        database,
        node_ids,
        current=current,
        cutoffs=cutoffs,
    )
    if node_ids:
        placeholders = ",".join("?" for _ in node_ids)
        window_values = ",".join("(?,?,?)" for _ in LATENCY_WINDOWS)
        aggregate_rows = database.fetch_all(
            "WITH samples("
            "node_id,sampled_at,availability_samples,online_samples,"
            "node_latency_sum,node_latency_samples,"
            "website_latency_sum,website_latency_samples"
            ") AS ("
            " SELECT node_id,finished_at,"
            "CASE WHEN node_probe_status IS NOT NULL THEN 1 ELSE 0 END,"
            "CASE WHEN node_probe_status IS NOT NULL "
            "AND status IN ('online','degraded') THEN 1 ELSE 0 END,"
            "CASE WHEN node_latency_ms IS NOT NULL THEN node_latency_ms ELSE 0 END,"
            "CASE WHEN node_latency_ms IS NOT NULL THEN 1 ELSE 0 END,"
            "CASE WHEN latency_avg_ms IS NOT NULL THEN latency_avg_ms ELSE 0 END,"
            "CASE WHEN latency_avg_ms IS NOT NULL THEN 1 ELSE 0 END "
            f"FROM check_runs WHERE finished_at>=? AND node_id IN ({placeholders}) "
            "UNION ALL "
            "SELECT node_id,bucket_at,node_probe_samples,node_online_samples,"
            "COALESCE(node_latency_avg_ms,0)*node_probe_samples,"
            "CASE WHEN node_latency_avg_ms IS NOT NULL "
            "THEN node_probe_samples ELSE 0 END,"
            "COALESCE(latency_avg_ms,0)*samples,"
            "CASE WHEN latency_avg_ms IS NOT NULL THEN samples ELSE 0 END "
            f"FROM hourly_stats WHERE bucket_at>=? AND node_id IN ({placeholders})"
            "), windows(window_key,hours,cutoff) AS ("
            f"VALUES {window_values}"
            ") SELECT samples.node_id,windows.window_key,windows.hours,"
            "SUM(samples.availability_samples) AS availability_samples,"
            "SUM(samples.online_samples) AS online_samples,"
            "SUM(samples.node_latency_sum) AS node_latency_sum,"
            "SUM(samples.node_latency_samples) AS node_latency_samples,"
            "SUM(samples.website_latency_sum) AS website_latency_sum,"
            "SUM(samples.website_latency_samples) AS website_latency_samples,"
            "MIN(samples.sampled_at) AS first_sample_at,"
            "MAX(samples.sampled_at) AS last_sample_at "
            "FROM samples JOIN windows ON samples.sampled_at>=windows.cutoff "
            "GROUP BY samples.node_id,windows.window_key,windows.hours",
            tuple(
                [cutoffs["720h"], *node_ids, cutoffs["720h"], *node_ids]
                + [
                    value
                    for key, hours, _ in LATENCY_WINDOWS
                    for value in (key, hours, cutoffs[key])
                ]
            ),
        )
        for aggregate in aggregate_rows:
            node_id = int(aggregate["node_id"])
            window_key = str(aggregate["window_key"])
            reliability = reliability_by_window.get(window_key, {}).get(
                node_id,
                {},
            )
            quality = quality_by_node.get(node_id, {}).get(window_key, {})
            availability_samples = int(
                reliability.get("availability_samples")
                or aggregate["availability_samples"]
                or 0
            )
            node_latency_samples = int(
                aggregate["node_latency_samples"] or 0
            )
            website_latency_samples = int(
                aggregate["website_latency_samples"] or 0
            )
            availability = reliability.get("availability")
            node_latency = (
                round(
                    float(aggregate["node_latency_sum"] or 0)
                    / node_latency_samples,
                    2,
                )
                if node_latency_samples
                else None
            )
            website_latency = (
                round(
                    float(aggregate["website_latency_sum"] or 0)
                    / website_latency_samples,
                    2,
                )
                if website_latency_samples
                else None
            )
            score = _period_score(
                availability,
                quality.get("node_latency_p95_ms"),
                quality.get("website_latency_p95_ms"),
                website_availability=quality.get("website_availability"),
                node_jitter_ms=quality.get("node_jitter_p95_ms"),
                retry_rate=quality.get("retry_rate"),
            )
            by_node[node_id][window_key] = {
                "hours": int(aggregate["hours"]),
                "availability": availability,
                "availability_samples": availability_samples,
                "availability_observed_seconds": int(
                    reliability.get("availability_observed_seconds") or 0
                ),
                "coverage_percent": reliability.get("coverage_percent"),
                "confidence": reliability.get("confidence", "none"),
                "observer_offline_seconds": int(
                    reliability.get("observer_offline_seconds") or 0
                ),
                "unknown_seconds": int(
                    reliability.get("unknown_seconds") or 0
                ),
                "node_latency_ms": node_latency,
                "node_latency_samples": node_latency_samples,
                "node_latency_p95_ms": quality.get("node_latency_p95_ms"),
                "node_jitter_p95_ms": quality.get("node_jitter_p95_ms"),
                "website_latency_ms": website_latency,
                "website_latency_samples": website_latency_samples,
                "website_latency_p95_ms": quality.get(
                    "website_latency_p95_ms"
                ),
                "website_availability": quality.get(
                    "website_availability"
                ),
                "website_samples": int(
                    quality.get("website_samples") or 0
                ),
                "retry_rate": quality.get("retry_rate"),
                "score": score,
                "level": _score_level(score),
                "first_sample_at": aggregate["first_sample_at"],
                "last_sample_at": aggregate["last_sample_at"],
            }
    for node_id in node_ids:
        for key, hours, _label in LATENCY_WINDOWS:
            if key in by_node[node_id]:
                continue
            reliability = reliability_by_window.get(key, {}).get(node_id, {})
            quality = quality_by_node.get(node_id, {}).get(key, {})
            availability = reliability.get("availability")
            score = _period_score(
                availability,
                quality.get("node_latency_p95_ms"),
                quality.get("website_latency_p95_ms"),
                website_availability=quality.get("website_availability"),
                node_jitter_ms=quality.get("node_jitter_p95_ms"),
                retry_rate=quality.get("retry_rate"),
            )
            by_node[node_id][key] = {
                "hours": hours,
                "availability": availability,
                "availability_samples": int(
                    reliability.get("availability_samples") or 0
                ),
                "availability_observed_seconds": int(
                    reliability.get("availability_observed_seconds") or 0
                ),
                "coverage_percent": reliability.get("coverage_percent"),
                "confidence": reliability.get("confidence", "none"),
                "observer_offline_seconds": int(
                    reliability.get("observer_offline_seconds") or 0
                ),
                "unknown_seconds": int(
                    reliability.get("unknown_seconds") or 0
                ),
                "node_latency_ms": None,
                "node_latency_samples": 0,
                "node_latency_p95_ms": quality.get("node_latency_p95_ms"),
                "node_jitter_p95_ms": quality.get("node_jitter_p95_ms"),
                "website_latency_ms": None,
                "website_latency_samples": 0,
                "website_latency_p95_ms": quality.get(
                    "website_latency_p95_ms"
                ),
                "website_availability": quality.get(
                    "website_availability"
                ),
                "website_samples": int(quality.get("website_samples") or 0),
                "retry_rate": quality.get("retry_rate"),
                "score": score,
                "level": _score_level(score),
                "first_sample_at": None,
                "last_sample_at": None,
            }

    items: list[dict[str, Any]] = []
    for row in rows:
        node_periods = by_node.get(int(row["id"]), {})
        periods = []
        for key, hours, label in LATENCY_WINDOWS:
            period = node_periods.get(
                key,
                {
                    "hours": hours,
                    "availability": None,
                    "availability_samples": 0,
                    "availability_observed_seconds": 0,
                    "coverage_percent": 0.0,
                    "confidence": "none",
                    "observer_offline_seconds": 0,
                    "unknown_seconds": hours * 3600,
                    "node_latency_ms": None,
                    "node_latency_samples": 0,
                    "node_latency_p95_ms": None,
                    "node_jitter_p95_ms": None,
                    "website_latency_ms": None,
                    "website_latency_samples": 0,
                    "website_latency_p95_ms": None,
                    "website_availability": None,
                    "website_samples": 0,
                    "retry_rate": None,
                    "score": None,
                    "level": "unknown",
                    "first_sample_at": None,
                    "last_sample_at": None,
                },
            )
            periods.append({"key": key, "label": label, **period})
        overall = periods[-1]
        items.append(
            {
                **row,
                "periods": periods,
                "overall_score": overall["score"],
                "overall_level": overall["level"],
                "overall_availability": overall["availability"],
                "overall_node_latency_ms": overall["node_latency_ms"],
                "overall_node_latency_p95_ms": overall[
                    "node_latency_p95_ms"
                ],
                "overall_website_latency_ms": overall["website_latency_ms"],
                "overall_website_latency_p95_ms": overall[
                    "website_latency_p95_ms"
                ],
                "overall_website_availability": overall[
                    "website_availability"
                ],
                "overall_coverage_percent": overall["coverage_percent"],
                "overall_confidence": overall["confidence"],
                "overall_samples": overall["availability_samples"],
            }
        )

    numeric_sort_fields = {
        "score": "overall_score",
        "availability": "overall_availability",
        "node_latency": "overall_node_latency_p95_ms",
        "website_latency": "overall_website_latency_p95_ms",
    }
    descending = direction.lower() == "desc"
    if sort in {"name", "country"}:
        field = "name" if sort == "name" else "region_name"
        items.sort(
            key=lambda item: str(item.get(field) or "").casefold(),
            reverse=descending,
        )
    else:
        field = numeric_sort_fields.get(sort, "overall_score")

        def numeric_key(item: dict[str, Any]) -> tuple[bool, float, str]:
            value = item.get(field)
            missing = value is None or not math.isfinite(float(value))
            number = float(value) if not missing else 0.0
            return (
                missing,
                -number if descending else number,
                str(item["name"]).casefold(),
            )

        items.sort(key=numeric_key)

    total = len(items)
    pages = max(1, math.ceil(total / page_size))
    page = min(page, pages)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    scored = [
        item for item in items if item["overall_score"] is not None
    ]
    country_rows = database.fetch_all(
        "SELECT country_code,COUNT(*) AS count FROM nodes "
        "WHERE source_present=1"
        + (" AND enabled=1" if enabled_only else "")
        + " GROUP BY country_code"
    )
    return {
        "generated_at": current.isoformat(timespec="seconds"),
        "windows": [
            {"key": key, "hours": hours, "label": label}
            for key, hours, label in LATENCY_WINDOWS
        ],
        "summary": {
            "nodes_total": total,
            "nodes_scored": len(scored),
            "average_score": (
                round(
                    sum(float(item["overall_score"]) for item in scored)
                    / len(scored),
                    1,
                )
                if scored
                else None
            ),
            "availability_720h": _average_present(
                item["overall_availability"] for item in items
            ),
            "node_latency_720h_ms": _average_present(
                item["overall_node_latency_ms"] for item in items
            ),
            "website_latency_720h_ms": _average_present(
                item["overall_website_latency_ms"] for item in items
            ),
            "node_latency_p95_720h_ms": _average_present(
                item["overall_node_latency_p95_ms"] for item in items
            ),
            "website_latency_p95_720h_ms": _average_present(
                item["overall_website_latency_p95_ms"] for item in items
            ),
            "website_availability_720h": _average_present(
                item["overall_website_availability"] for item in items
            ),
            "coverage_720h": _average_present(
                item["overall_coverage_percent"] for item in items
            ),
            "best_node": (
                {
                    "id": max(
                        scored,
                        key=lambda item: float(item["overall_score"]),
                    )["id"],
                    "name": max(
                        scored,
                        key=lambda item: float(item["overall_score"]),
                    )["name"],
                    "score": max(
                        float(item["overall_score"]) for item in scored
                    ),
                }
                if scored
                else None
            ),
        },
        "score_definition": {
            "basis": "720h",
            "availability_weight": 45,
            "website_availability_weight": 20,
            "node_latency_weight": 15,
            "website_latency_weight": 10,
            "stability_weight": 10,
            "missing_values": "no_global_reweight",
            "node_latency_thresholds_ms": {
                "statistic": "p95",
                "good": 600,
                "acceptable": 1500,
                "maximum": 4000,
            },
            "website_latency_thresholds_ms": {
                "statistic": "p95",
                "good": 1800,
                "acceptable": 3500,
                "maximum": 8000,
            },
            "jitter_thresholds_ms": {
                "statistic": "p95",
                "good": 80,
                "acceptable": 250,
                "maximum": 800,
            },
        },
        "items": page_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "facets": {
            "countries": [
                {
                    **item,
                    "count": next(
                        (
                            int(row["count"])
                            for row in country_rows
                            if row["country_code"] == item["code"]
                        ),
                        0,
                    ),
                }
                for item in country_options(
                    row["country_code"] for row in country_rows
                )
            ]
        },
    }


def _average_present(values: Iterable[float | None]) -> float | None:
    available = [
        float(value)
        for value in values
        if value is not None and math.isfinite(float(value))
    ]
    return round(sum(available) / len(available), 2) if available else None


def trend(database: Database, days: int = 7) -> list[dict[str, Any]]:
    days = max(1, min(days, 30))
    cutoff = (utc_now() - timedelta(days=days)).isoformat(timespec="seconds")
    rows = database.fetch_all(
        "WITH points AS ("
        " SELECT substr(finished_at,1,13)||':00:00+00:00' AS bucket,"
        " SUM(CASE WHEN node_probe_status IS NOT NULL THEN 1 ELSE 0 END) AS samples,"
        " SUM(CASE WHEN node_probe_status IS NOT NULL "
        "AND status IN ('online','degraded') THEN 1 ELSE 0 END) AS online,"
        " SUM(CASE WHEN node_probe_status IS NOT NULL "
        "THEN health_score ELSE 0 END) AS health_sum,"
        " SUM(COALESCE(node_latency_ms,0)) AS latency_sum,"
        " SUM(CASE WHEN node_latency_ms IS NOT NULL THEN 1 ELSE 0 END) "
        "AS latency_samples,"
        " SUM(COALESCE(latency_avg_ms,0)) AS website_latency_sum,"
        " SUM(CASE WHEN latency_avg_ms IS NOT NULL THEN 1 ELSE 0 END) "
        "AS website_latency_samples"
        " FROM check_runs WHERE finished_at>=? GROUP BY bucket"
        " UNION ALL"
        " SELECT bucket_at,SUM(node_probe_samples),SUM(node_online_samples),"
        " SUM(COALESCE(node_health_avg,0)*node_probe_samples),"
        " SUM(COALESCE(node_latency_avg_ms,0)*node_probe_samples),"
        " SUM(CASE WHEN node_latency_avg_ms IS NOT NULL "
        "THEN node_probe_samples ELSE 0 END),"
        " SUM(COALESCE(latency_avg_ms,0)*samples),"
        " SUM(CASE WHEN latency_avg_ms IS NOT NULL THEN samples ELSE 0 END)"
        " FROM hourly_stats WHERE bucket_at>=? GROUP BY bucket_at"
        ") SELECT bucket,SUM(samples) AS samples,SUM(online) AS online,"
        "SUM(health_sum) AS health_sum,SUM(latency_sum) AS latency_sum,"
        "SUM(latency_samples) AS latency_samples,"
        "SUM(website_latency_sum) AS website_latency_sum,"
        "SUM(website_latency_samples) AS website_latency_samples FROM points "
        "GROUP BY bucket ORDER BY bucket",
        (cutoff, cutoff),
    )
    return [_trend_row(row, time_key="bucket") for row in rows]


def _trend_row(row: dict[str, Any], *, time_key: str) -> dict[str, Any]:
    samples = int(row["samples"] or 0)
    latency_samples = int(row.get("latency_samples") or 0)
    website_latency_samples = int(row.get("website_latency_samples") or 0)
    return {
        "time": row[time_key],
        "samples": samples,
        "availability": (
            round(100 * int(row["online"] or 0) / samples, 2) if samples else None
        ),
        "health": (
            round(float(row["health_sum"] or 0) / samples, 2)
            if samples
            else None
        ),
        "latency_ms": (
            round(float(row["latency_sum"] or 0) / latency_samples, 2)
            if latency_samples
            else None
        ),
        "website_latency_ms": (
            round(
                float(row.get("website_latency_sum") or 0)
                / website_latency_samples,
                2,
            )
            if website_latency_samples
            else None
        ),
    }


def node_trend(
    database: Database,
    node_id: int,
    days: int = 7,
) -> list[dict[str, Any]]:
    days = max(1, min(days, 30))
    cutoff = (utc_now() - timedelta(days=days)).isoformat(timespec="seconds")
    rows = database.fetch_all(
        "SELECT finished_at AS time,"
        "CASE WHEN node_probe_status IS NOT NULL THEN health_score END AS health,"
        "node_latency_ms AS latency,latency_avg_ms AS website_latency,"
        "CASE WHEN node_probe_status IS NOT NULL THEN 1 ELSE 0 END AS samples,"
        "CASE WHEN node_probe_status IS NOT NULL "
        "AND status IN ('online','degraded') THEN 1 ELSE 0 END AS online,"
        "CASE WHEN latency_avg_ms IS NOT NULL THEN 1 ELSE 0 END AS website_samples "
        "FROM check_runs WHERE node_id=? AND finished_at>=? "
        "UNION ALL "
        "SELECT bucket_at,node_health_avg,node_latency_avg_ms,latency_avg_ms,"
        "node_probe_samples,node_online_samples,"
        "CASE WHEN latency_avg_ms IS NOT NULL THEN samples ELSE 0 END "
        "FROM hourly_stats WHERE node_id=? AND bucket_at>=? ORDER BY time",
        (node_id, cutoff, node_id, cutoff),
    )
    bucket_seconds = 900 if days <= 1 else 3600 if days <= 7 else 10800 if days <= 20 else 21600
    buckets: dict[int, dict[str, Any]] = {}
    for row in rows:
        parsed = parse_time(row["time"])
        if not parsed:
            continue
        stamp = int(parsed.timestamp())
        bucket = stamp - stamp % bucket_seconds
        item = buckets.setdefault(
            bucket,
            {
                "samples": 0,
                "online": 0,
                "health_sum": 0.0,
                "latency_sum": 0.0,
                "latency_samples": 0,
                "website_latency_sum": 0.0,
                "website_latency_samples": 0,
            },
        )
        samples = int(row["samples"] or 0)
        item["samples"] += samples
        item["online"] += int(row["online"] or 0)
        item["health_sum"] += float(row["health"] or 0) * samples
        if row["latency"] is not None:
            item["latency_sum"] += float(row["latency"]) * samples
            item["latency_samples"] += samples
        website_samples = int(row["website_samples"] or 0)
        if row["website_latency"] is not None and website_samples:
            item["website_latency_sum"] += (
                float(row["website_latency"]) * website_samples
            )
            item["website_latency_samples"] += website_samples
    points = []
    for bucket, values in sorted(buckets.items()):
        values["time"] = datetime.fromtimestamp(bucket, UTC).isoformat(
            timespec="seconds"
        )
        points.append(_trend_row(values, time_key="time"))
    return points[-192:]


def list_events(database: Database, limit: int = 100) -> list[dict[str, Any]]:
    return database.fetch_all(
        "SELECT e.id,e.event_type,e.severity,e.title,e.detail,e.created_at,"
        "e.recovered_at,n.id AS node_id,n.name AS node_name,"
        "s.id AS subscription_id,s.name AS subscription_name "
        "FROM events e LEFT JOIN nodes n ON n.id=e.node_id "
        "LEFT JOIN subscriptions s ON s.id=COALESCE(e.subscription_id,n.subscription_id) "
        "ORDER BY e.created_at DESC LIMIT ?",
        (max(1, min(limit, 500)),),
    )


def dashboard(database: Database) -> dict[str, Any]:
    nodes = list_nodes(database)
    active = [node for node in nodes if node["enabled"]]
    healthy = [node for node in active if node["current_status"] == "online"]
    degraded = [node for node in active if node["current_status"] == "degraded"]
    online = [
        node for node in active if node["current_status"] in {"online", "degraded"}
    ]
    checked = [node for node in active if node["last_checked_at"]]
    overall_health = (
        round(sum(float(node["health_score"]) for node in checked) / len(checked), 1)
        if checked
        else 0.0
    )
    target_keys = _enabled_target_keys(database)
    service_rates: dict[str, dict[str, Any]] = {}
    if target_keys:
        placeholders = ",".join("?" for _ in target_keys)
        rows = database.fetch_all(
            "WITH latest AS ("
            " SELECT node_id,MAX(id) AS run_id FROM check_runs GROUP BY node_id"
            ") SELECT sr.service,COUNT(*) AS total,SUM(sr.reachable) AS reachable,"
            "AVG(sr.latency_ms) AS latency FROM latest "
            "JOIN nodes n ON n.id=latest.node_id "
            "AND n.source_present=1 AND n.enabled=1 "
            "JOIN service_results sr ON sr.check_run_id=latest.run_id "
            f"WHERE sr.service IN ({placeholders}) GROUP BY sr.service",
            target_keys,
        )
        service_rates = {
            row["service"]: {
                "total": int(row["total"]),
                "reachable": int(row["reachable"] or 0),
                "rate": (
                    round(
                        100 * int(row["reachable"] or 0) / int(row["total"]),
                        1,
                    )
                    if row["total"]
                    else 0.0
                ),
                "latency_ms": (
                    round(float(row["latency"]), 1)
                    if row["latency"] is not None
                    else None
                ),
            }
            for row in rows
        }
    metrics = database.fetch_one(
        "SELECT * FROM system_metrics ORDER BY sampled_at DESC LIMIT 1"
    )
    task_rows = database.fetch_all(
        "SELECT id,kind,status,total,completed,succeeded,failed,created_at,"
        "started_at,finished_at,message FROM tasks ORDER BY created_at DESC LIMIT 8"
    )
    settings = database.get_settings()
    monitor_row = database.fetch_one(
        "SELECT MAX(last_checked_at) AS last_check_at,"
        "MIN(next_check_at) AS next_check_at "
        "FROM nodes WHERE enabled=1 AND source_present=1"
    )
    scheduled_cutoff = (utc_now() - timedelta(days=1)).isoformat(timespec="seconds")
    scheduled_row = database.fetch_one(
        "SELECT COUNT(cr.id) AS checks,MAX(cr.finished_at) AS last_scheduled_at "
        "FROM check_runs cr JOIN tasks t ON t.id=cr.task_id "
        "WHERE t.kind='scheduled_check' AND cr.finished_at>=?",
        (scheduled_cutoff,),
    )
    observer_row = database.fetch_one(
        "SELECT sampled_at,status,interface,reason FROM observer_samples "
        "ORDER BY sampled_at DESC LIMIT 1"
    )
    return {
        "generated_at": iso_now(),
        "summary": {
            "health": overall_health,
            "nodes_total": len(active),
            "nodes_online": len(online),
            "nodes_healthy": len(healthy),
            "nodes_degraded": len(degraded),
            "nodes_offline": sum(
                node["current_status"] == "offline" for node in active
            ),
            "nodes_pending": sum(
                node["current_status"] in {"pending", "unknown"} for node in active
            ),
            "availability_24h": _overall_availability(nodes, "availability_24h"),
            "availability_7d": _overall_availability(nodes, "availability_7d"),
            "availability_30d": _overall_availability(nodes, "availability_30d"),
        },
        "service_rates": service_rates,
        "trend": trend(database, 7),
        "fault_nodes": [
            node
            for node in active
            if node["current_status"] in {"offline", "degraded", "unknown"}
        ][:8],
        "events": list_events(database, 12),
        "system": metrics,
        "tasks": task_rows,
        "monitoring": {
            "scheduler_paused": bool(settings["scheduler_paused"]),
            "node_probe_enabled": bool(settings["node_probe_enabled"]),
            "check_interval_minutes": int(settings["check_interval_minutes"]),
            "offline_check_interval_minutes": int(
                settings["offline_check_interval_minutes"]
            ),
            "jitter_seconds": int(settings["jitter_seconds"]),
            "enabled_targets": list(target_keys),
            "last_check_at": monitor_row["last_check_at"] if monitor_row else None,
            "next_check_at": monitor_row["next_check_at"] if monitor_row else None,
            "scheduled_checks_24h": (
                int(scheduled_row["checks"] or 0) if scheduled_row else 0
            ),
            "last_scheduled_at": (
                scheduled_row["last_scheduled_at"] if scheduled_row else None
            ),
            "observer": observer_row,
        },
    }


def node_detail(database: Database, node_id: int) -> dict[str, Any] | None:
    row = database.fetch_one(
        "SELECT n.id,n.name,n.protocol,n.endpoint_mask,n.enabled,n.source_present,"
        "n.current_status,n.health_score,n.last_latency_ms,"
        "n.last_website_latency_ms,n.last_node_jitter_ms,"
        "n.last_node_probe_status,n.last_node_probe_successes,"
        "n.last_node_probe_samples,n.last_node_probe_target,"
        "n.last_node_latency_method,n.last_node_endpoint_status,"
        "n.last_node_endpoint_successes,n.last_node_endpoint_samples,"
        "n.last_node_endpoint_latency_ms,n.last_node_endpoint_latency_p95_ms,"
        "n.last_node_endpoint_jitter_ms,n.online_since,"
        "n.last_checked_at,n.next_check_at,n.last_failure_at,n.last_recovery_at,"
        "n.consecutive_failures,n.circuit_open_until,n.last_error_type,"
        "n.country_code,n.region_name,n.location_source,n.location_checked_at,"
        "n.location_provider_count,n.exit_ip_mask,s.id AS subscription_id,"
        "s.name AS subscription_name FROM nodes n "
        "JOIN subscriptions s ON s.id=n.subscription_id "
        "WHERE n.id=? AND n.source_present=1",
        (node_id,),
    )
    if not row:
        return None
    _decorate_nodes(database, [row])
    runs = database.fetch_all(
        "SELECT id,task_id,started_at,finished_at,status,health_score,"
        "latency_avg_ms,latency_p50_ms,latency_p95_ms,error_type,attempt_count,"
        "website_status,website_health_score,website_error_type,"
        "node_probe_status,node_latency_ms,node_latency_p50_ms,"
        "node_latency_p95_ms,node_jitter_ms,node_probe_successes,"
        "node_probe_samples,node_probe_http_code,node_probe_target,"
        "node_probe_error_type,node_latency_method,node_endpoint_status,"
        "node_endpoint_successes,node_endpoint_samples,"
        "node_endpoint_latency_ms,node_endpoint_latency_p50_ms,"
        "node_endpoint_latency_p95_ms,node_endpoint_jitter_ms "
        "FROM check_runs WHERE node_id=? ORDER BY finished_at DESC LIMIT 50",
        (node_id,),
    )
    services: list[dict[str, Any]] = []
    if runs:
        run_placeholders = ",".join("?" for _ in runs)
        targets = _enabled_target_keys(database)
        service_placeholders = ",".join("?" for _ in targets)
        services = database.fetch_all(
            "SELECT check_run_id,service,status,reachable,dns_ok,tcp_ok,tls_ok,"
            "http_code,latency_ms,dns_ms,tcp_ms,tls_ms,ttfb_ms,redirect_count,"
            "final_host_class,feature_ok,error_type FROM service_results "
            f"WHERE check_run_id IN ({run_placeholders}) "
            f"AND service IN ({service_placeholders}) "
            "ORDER BY check_run_id DESC,service",
            tuple(item["id"] for item in runs) + targets,
        )
    by_run: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for service_result in services:
        if service_result["status"] == "captcha":
            service_result["status"] = "available"
            service_result["error_type"] = None
        for key in ("reachable", "dns_ok", "tcp_ok", "tls_ok", "feature_ok"):
            service_result[key] = bool(service_result[key])
        service_result["level"] = SERVICE_LEVELS.get(
            service_result["status"], "unknown"
        )
        by_run[int(service_result["check_run_id"])].append(service_result)
    for run in runs:
        run["services"] = by_run.get(int(run["id"]), [])
    return {
        "node": row,
        "runs": runs,
        "trend": node_trend(database, node_id, 7),
        "events": database.fetch_all(
            "SELECT id,event_type,severity,title,detail,created_at,recovered_at "
            "FROM events WHERE node_id=? ORDER BY created_at DESC LIMIT 50",
            (node_id,),
        ),
    }


def system_status(
    database: Database,
    storage: StorageManager,
) -> dict[str, Any]:
    current = database.fetch_one(
        "SELECT * FROM system_metrics ORDER BY sampled_at DESC LIMIT 1"
    )
    series = database.fetch_all(
        "SELECT * FROM system_metrics ORDER BY sampled_at DESC LIMIT 120"
    )
    series.reverse()
    counts = database.fetch_one(
        "SELECT (SELECT COUNT(*) FROM check_runs) AS checks,"
        "(SELECT COUNT(*) FROM service_results) AS service_results,"
        "(SELECT COUNT(*) FROM events) AS events,"
        "(SELECT COUNT(*) FROM nodes WHERE source_present=1) AS nodes,"
        "(SELECT COUNT(*) FROM hourly_stats) AS hourly_stats,"
        "(SELECT COUNT(*) FROM observer_samples) AS observer_samples"
    )
    maintenance = database.fetch_one(
        "SELECT reason,status,started_at,finished_at,before_bytes,after_bytes,"
        "freed_bytes,deleted_runs,deleted_metrics,deleted_tasks,deleted_events,detail "
        "FROM maintenance_runs ORDER BY finished_at DESC LIMIT 1"
    )
    settings = database.get_settings()
    observer = database.fetch_one(
        "SELECT sampled_at,status,interface,reason FROM observer_samples "
        "ORDER BY sampled_at DESC LIMIT 1"
    )
    return {
        "current": current,
        "series": series,
        "database_bytes": database.allocated_bytes(),
        "counts": counts,
        "storage": storage.snapshot().as_dict(),
        "retention": {
            "raw_days": int(settings["raw_retention_days"]),
            "hourly_days": int(settings["hourly_retention_days"]),
            "metrics_days": 7,
            "task_days": 30,
        },
        "last_maintenance": maintenance,
        "observer": observer,
    }


def _overall_availability(
    nodes: list[dict[str, Any]], field: str
) -> float | None:
    values = [
        float(node[field])
        for node in nodes
        if node["enabled"] and node.get(field) is not None
    ]
    return round(sum(values) / len(values), 2) if values else None
