-- 2.1.5 起，安全挑战中间页只代表目标网站已经成功响应，不再作为
-- 节点降级项。升级时将旧记录折算为“已到达”，避免旧口径继续污染
-- 当前节点状态和近期健康曲线。

CREATE TEMP TABLE legacy_interstitial_runs AS
SELECT
    cr.id AS run_id,
    cr.node_id AS node_id,
    SUM(CASE WHEN sr.status = 'captcha' THEN 1 ELSE 0 END) AS legacy_count,
    COUNT(sr.id) AS total_count
FROM check_runs cr
JOIN service_results sr ON sr.check_run_id = cr.id
GROUP BY cr.id, cr.node_id
HAVING legacy_count > 0;

UPDATE check_runs
SET
    health_score = MIN(
        100.0,
        ROUND(
            health_score + 9.0 * (
                SELECT legacy_count * 1.0 / NULLIF(total_count, 0)
                FROM legacy_interstitial_runs legacy
                WHERE legacy.run_id = check_runs.id
            ),
            1
        )
    ),
    error_type = CASE
        WHEN error_type = 'captcha' THEN (
            SELECT COALESCE(NULLIF(sr.error_type, ''), sr.status)
            FROM service_results sr
            WHERE sr.check_run_id = check_runs.id
              AND sr.status NOT IN ('available', 'captcha')
            ORDER BY sr.reachable ASC, sr.id
            LIMIT 1
        )
        ELSE error_type
    END
WHERE id IN (SELECT run_id FROM legacy_interstitial_runs);

UPDATE check_runs
SET status = 'online', health_score = 100.0, error_type = NULL
WHERE id IN (SELECT run_id FROM legacy_interstitial_runs)
  AND NOT EXISTS (
      SELECT 1
      FROM service_results sr
      WHERE sr.check_run_id = check_runs.id
        AND (sr.reachable = 0 OR sr.status NOT IN ('available', 'captcha'))
  );

UPDATE service_results
SET status = 'available', reachable = 1, error_type = NULL
WHERE status = 'captcha' OR error_type = 'captcha';

UPDATE nodes
SET
    current_status = (
        SELECT cr.status
        FROM check_runs cr
        WHERE cr.node_id = nodes.id
        ORDER BY cr.finished_at DESC, cr.id DESC
        LIMIT 1
    ),
    health_score = (
        SELECT cr.health_score
        FROM check_runs cr
        WHERE cr.node_id = nodes.id
        ORDER BY cr.finished_at DESC, cr.id DESC
        LIMIT 1
    ),
    last_error_type = (
        SELECT cr.error_type
        FROM check_runs cr
        WHERE cr.node_id = nodes.id
        ORDER BY cr.finished_at DESC, cr.id DESC
        LIMIT 1
    ),
    consecutive_failures = CASE
        WHEN (
            SELECT cr.status
            FROM check_runs cr
            WHERE cr.node_id = nodes.id
            ORDER BY cr.finished_at DESC, cr.id DESC
            LIMIT 1
        ) = 'online' THEN 0
        ELSE consecutive_failures
    END,
    circuit_open_until = CASE
        WHEN (
            SELECT cr.status
            FROM check_runs cr
            WHERE cr.node_id = nodes.id
            ORDER BY cr.finished_at DESC, cr.id DESC
            LIMIT 1
        ) = 'online' THEN NULL
        ELSE circuit_open_until
    END
WHERE (
    SELECT cr.id
    FROM check_runs cr
    WHERE cr.node_id = nodes.id
    ORDER BY cr.finished_at DESC, cr.id DESC
    LIMIT 1
) IN (SELECT run_id FROM legacy_interstitial_runs);

DROP TABLE legacy_interstitial_runs;
