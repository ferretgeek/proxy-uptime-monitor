-- 2.3.0：离线节点必须持续复测；监测机自身不可联网时不再把所有节点误判为故障。

CREATE TABLE IF NOT EXISTS observer_samples (
    sampled_at TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK(status IN ('online', 'offline', 'unknown')),
    interface TEXT,
    reason TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observer_samples_time
    ON observer_samples(sampled_at DESC);

-- 旧数据没有监测机链路采样。用实际执行过节点检测的分钟回填为“可观测”，
-- 正常错峰检测会形成连续覆盖，长时间没有任何检测的区间仍会保留为未知。
INSERT OR IGNORE INTO observer_samples(sampled_at,status,interface,reason)
SELECT
    substr(finished_at,1,16)||':00+00:00',
    'online',
    NULL,
    'legacy_check_activity'
FROM check_runs
GROUP BY substr(finished_at,1,16);

ALTER TABLE hourly_stats ADD COLUMN service_samples INTEGER NOT NULL DEFAULT 0;
ALTER TABLE hourly_stats ADD COLUMN service_reachable_samples INTEGER NOT NULL DEFAULT 0;
ALTER TABLE hourly_stats ADD COLUMN retry_samples INTEGER NOT NULL DEFAULT 0;
ALTER TABLE hourly_stats ADD COLUMN node_jitter_avg_ms REAL;
ALTER TABLE hourly_stats ADD COLUMN node_jitter_p95_ms REAL;

-- 旧熔断截止时间不再参与调度，升级后让所有启用节点立即恢复检测。
UPDATE nodes
SET circuit_open_until = NULL,
    next_check_at = CASE
        WHEN enabled = 1 AND source_present = 1 THEN
            strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
        ELSE next_check_at
    END;

DELETE FROM app_settings WHERE key='breaker_threshold';
