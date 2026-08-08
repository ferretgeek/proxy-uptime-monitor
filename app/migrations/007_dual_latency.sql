-- 网站完整访问耗时与轻量节点测速使用不同口径。旧字段保留网站耗时，
-- 新字段只接收升级后的真实轻量测速，避免用历史页面加载时间冒充节点延迟。

ALTER TABLE nodes ADD COLUMN last_website_latency_ms REAL;
ALTER TABLE nodes ADD COLUMN last_node_jitter_ms REAL;
ALTER TABLE nodes ADD COLUMN last_node_probe_status TEXT;
ALTER TABLE nodes ADD COLUMN last_node_probe_successes INTEGER;
ALTER TABLE nodes ADD COLUMN last_node_probe_samples INTEGER;
ALTER TABLE nodes ADD COLUMN last_node_probe_target TEXT;

UPDATE nodes
SET last_website_latency_ms = last_latency_ms,
    last_latency_ms = NULL;

ALTER TABLE check_runs ADD COLUMN website_status TEXT;
ALTER TABLE check_runs ADD COLUMN website_health_score REAL;
ALTER TABLE check_runs ADD COLUMN website_error_type TEXT;
ALTER TABLE check_runs ADD COLUMN node_probe_status TEXT;
ALTER TABLE check_runs ADD COLUMN node_latency_ms REAL;
ALTER TABLE check_runs ADD COLUMN node_latency_p50_ms REAL;
ALTER TABLE check_runs ADD COLUMN node_latency_p95_ms REAL;
ALTER TABLE check_runs ADD COLUMN node_jitter_ms REAL;
ALTER TABLE check_runs ADD COLUMN node_probe_successes INTEGER;
ALTER TABLE check_runs ADD COLUMN node_probe_samples INTEGER;
ALTER TABLE check_runs ADD COLUMN node_probe_http_code INTEGER;
ALTER TABLE check_runs ADD COLUMN node_probe_target TEXT;
ALTER TABLE check_runs ADD COLUMN node_probe_error_type TEXT;

UPDATE check_runs
SET website_status = status,
    website_health_score = health_score,
    website_error_type = error_type;

ALTER TABLE hourly_stats ADD COLUMN node_probe_samples INTEGER NOT NULL DEFAULT 0;
ALTER TABLE hourly_stats ADD COLUMN node_online_samples INTEGER NOT NULL DEFAULT 0;
ALTER TABLE hourly_stats ADD COLUMN node_health_avg REAL;
ALTER TABLE hourly_stats ADD COLUMN node_latency_avg_ms REAL;
ALTER TABLE hourly_stats ADD COLUMN node_latency_p50_ms REAL;
ALTER TABLE hourly_stats ADD COLUMN node_latency_p95_ms REAL;

CREATE INDEX IF NOT EXISTS idx_check_runs_node_probe_time
    ON check_runs(node_id, node_probe_status, finished_at DESC);
