-- “本地到节点”的主指标必须经过完整代理协议通道。旧版 tcp_connect 数值
-- 只代表订阅端点或 CDN/Anycast 入口握手，迁移到独立诊断字段后不再参与
-- 主延迟、趋势和健康判定。

ALTER TABLE nodes ADD COLUMN last_node_endpoint_latency_ms REAL;
ALTER TABLE nodes ADD COLUMN last_node_endpoint_latency_p95_ms REAL;
ALTER TABLE nodes ADD COLUMN last_node_endpoint_jitter_ms REAL;

ALTER TABLE check_runs ADD COLUMN node_endpoint_latency_ms REAL;
ALTER TABLE check_runs ADD COLUMN node_endpoint_latency_p50_ms REAL;
ALTER TABLE check_runs ADD COLUMN node_endpoint_latency_p95_ms REAL;
ALTER TABLE check_runs ADD COLUMN node_endpoint_jitter_ms REAL;

UPDATE nodes
SET last_node_endpoint_latency_ms = last_latency_ms,
    last_node_endpoint_jitter_ms = last_node_jitter_ms,
    last_latency_ms = NULL,
    last_node_jitter_ms = NULL,
    last_node_latency_method = NULL
WHERE last_node_latency_method = 'tcp_connect';

UPDATE check_runs
SET node_endpoint_latency_ms = node_latency_ms,
    node_endpoint_latency_p50_ms = node_latency_p50_ms,
    node_endpoint_latency_p95_ms = node_latency_p95_ms,
    node_endpoint_jitter_ms = node_jitter_ms,
    node_latency_ms = NULL,
    node_latency_p50_ms = NULL,
    node_latency_p95_ms = NULL,
    node_jitter_ms = NULL,
    node_latency_method = 'endpoint_only_legacy'
WHERE node_latency_method = 'tcp_connect';

UPDATE nodes
SET last_node_latency_method = 'protocol_urltest'
WHERE last_node_latency_method = 'protocol_urltest_fallback';

UPDATE check_runs
SET node_latency_method = 'protocol_urltest'
WHERE node_latency_method = 'protocol_urltest_fallback';

UPDATE hourly_stats
SET node_latency_avg_ms = NULL,
    node_latency_p50_ms = NULL,
    node_latency_p95_ms = NULL;
