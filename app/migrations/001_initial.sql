PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA temp_store = MEMORY;
PRAGMA auto_vacuum = INCREMENTAL;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    admin_id INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
    csrf_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    remote_fingerprint TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url_encrypted TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    refresh_interval_minutes INTEGER NOT NULL DEFAULT 360,
    last_refresh_at TEXT,
    next_refresh_at TEXT,
    last_error_type TEXT,
    last_error_message TEXT,
    node_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_due
    ON subscriptions(enabled, next_refresh_at);

CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    name TEXT NOT NULL,
    protocol TEXT NOT NULL,
    endpoint_mask TEXT NOT NULL,
    config_encrypted TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    source_present INTEGER NOT NULL DEFAULT 1 CHECK(source_present IN (0, 1)),
    current_status TEXT NOT NULL DEFAULT 'pending',
    health_score REAL NOT NULL DEFAULT 0,
    last_latency_ms REAL,
    online_since TEXT,
    last_checked_at TEXT,
    next_check_at TEXT,
    last_failure_at TEXT,
    last_recovery_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    circuit_open_until TEXT,
    last_error_type TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(subscription_id, fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_nodes_due
    ON nodes(enabled, source_present, next_check_at);
CREATE INDEX IF NOT EXISTS idx_nodes_status
    ON nodes(current_status, health_score DESC);
CREATE INDEX IF NOT EXISTS idx_nodes_subscription
    ON nodes(subscription_id);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    succeeded INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    requested_by TEXT NOT NULL,
    message TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);

CREATE TABLE IF NOT EXISTS check_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,
    health_score REAL NOT NULL,
    latency_avg_ms REAL,
    latency_p50_ms REAL,
    latency_p95_ms REAL,
    error_type TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_check_runs_node_time
    ON check_runs(node_id, finished_at DESC);
CREATE INDEX IF NOT EXISTS idx_check_runs_time
    ON check_runs(finished_at DESC);
CREATE INDEX IF NOT EXISTS idx_check_runs_task
    ON check_runs(task_id);

CREATE TABLE IF NOT EXISTS service_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    check_run_id INTEGER NOT NULL REFERENCES check_runs(id) ON DELETE CASCADE,
    service TEXT NOT NULL,
    status TEXT NOT NULL,
    reachable INTEGER NOT NULL CHECK(reachable IN (0, 1)),
    dns_ok INTEGER NOT NULL CHECK(dns_ok IN (0, 1)),
    tcp_ok INTEGER NOT NULL CHECK(tcp_ok IN (0, 1)),
    tls_ok INTEGER NOT NULL CHECK(tls_ok IN (0, 1)),
    http_code INTEGER,
    latency_ms REAL,
    dns_ms REAL,
    tcp_ms REAL,
    tls_ms REAL,
    ttfb_ms REAL,
    redirect_count INTEGER NOT NULL DEFAULT 0,
    final_host_class TEXT,
    feature_ok INTEGER NOT NULL CHECK(feature_ok IN (0, 1)),
    error_type TEXT
);
CREATE INDEX IF NOT EXISTS idx_service_results_run
    ON service_results(check_run_id);
CREATE INDEX IF NOT EXISTS idx_service_results_service_status
    ON service_results(service, status);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER REFERENCES nodes(id) ON DELETE CASCADE,
    subscription_id INTEGER REFERENCES subscriptions(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL,
    recovered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_open
    ON events(event_type, recovered_at, created_at DESC);

CREATE TABLE IF NOT EXISTS hourly_stats (
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    bucket_at TEXT NOT NULL,
    samples INTEGER NOT NULL,
    online_samples INTEGER NOT NULL,
    health_avg REAL NOT NULL,
    latency_avg_ms REAL,
    latency_p50_ms REAL,
    latency_p95_ms REAL,
    PRIMARY KEY(node_id, bucket_at)
);
CREATE INDEX IF NOT EXISTS idx_hourly_stats_time
    ON hourly_stats(bucket_at DESC);

CREATE TABLE IF NOT EXISTS system_metrics (
    sampled_at TEXT PRIMARY KEY,
    system_cpu_percent REAL NOT NULL,
    system_memory_percent REAL NOT NULL,
    system_memory_used_mb REAL NOT NULL,
    disk_percent REAL NOT NULL,
    disk_free_gb REAL NOT NULL,
    process_cpu_percent REAL NOT NULL,
    process_memory_mb REAL NOT NULL,
    active_checks INTEGER NOT NULL,
    queue_depth INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_system_metrics_time
    ON system_metrics(sampled_at DESC);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_config (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
    endpoint_encrypted TEXT,
    event_types_json TEXT NOT NULL DEFAULT '["failure","recovery"]',
    cooldown_minutes INTEGER NOT NULL DEFAULT 30,
    updated_at TEXT NOT NULL
);

