-- 2.2.0 的轻量 URL 测速仍包含节点之后的公网测速站往返，不能作为
-- “本地到节点”直连延迟。保留其代理通道可用状态，但清空混合口径的延迟，
-- 从本迁移后的真实端点握手开始重新累计趋势。

ALTER TABLE nodes ADD COLUMN last_node_latency_method TEXT;
ALTER TABLE nodes ADD COLUMN last_node_endpoint_status TEXT;
ALTER TABLE nodes ADD COLUMN last_node_endpoint_successes INTEGER;
ALTER TABLE nodes ADD COLUMN last_node_endpoint_samples INTEGER;

ALTER TABLE check_runs ADD COLUMN node_latency_method TEXT;
ALTER TABLE check_runs ADD COLUMN node_endpoint_status TEXT;
ALTER TABLE check_runs ADD COLUMN node_endpoint_successes INTEGER;
ALTER TABLE check_runs ADD COLUMN node_endpoint_samples INTEGER;

UPDATE nodes
SET last_latency_ms = NULL,
    last_node_jitter_ms = NULL
WHERE last_node_probe_target IN ('Google 204', 'Cloudflare 204', '自动备用');

UPDATE check_runs
SET node_latency_ms = NULL,
    node_latency_p50_ms = NULL,
    node_latency_p95_ms = NULL,
    node_jitter_ms = NULL
WHERE node_probe_target IN ('Google 204', 'Cloudflare 204', '自动备用');

UPDATE hourly_stats
SET node_latency_avg_ms = NULL,
    node_latency_p50_ms = NULL,
    node_latency_p95_ms = NULL;
