ALTER TABLE nodes ADD COLUMN country_code TEXT NOT NULL DEFAULT 'ZZ';
ALTER TABLE nodes ADD COLUMN region_name TEXT NOT NULL DEFAULT '未知地区';

CREATE INDEX IF NOT EXISTS idx_nodes_country_status
    ON nodes(country_code, current_status, enabled, source_present);
CREATE INDEX IF NOT EXISTS idx_check_runs_status_time
    ON check_runs(status, finished_at DESC);
CREATE INDEX IF NOT EXISTS idx_service_results_run_service
    ON service_results(check_run_id, service);
CREATE INDEX IF NOT EXISTS idx_tasks_status_created
    ON tasks(status, created_at DESC);

CREATE TABLE IF NOT EXISTS maintenance_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    before_bytes INTEGER NOT NULL DEFAULT 0,
    after_bytes INTEGER NOT NULL DEFAULT 0,
    freed_bytes INTEGER NOT NULL DEFAULT 0,
    deleted_runs INTEGER NOT NULL DEFAULT 0,
    deleted_metrics INTEGER NOT NULL DEFAULT 0,
    deleted_tasks INTEGER NOT NULL DEFAULT 0,
    deleted_events INTEGER NOT NULL DEFAULT 0,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_maintenance_finished
    ON maintenance_runs(finished_at DESC);

UPDATE app_settings
SET value_json='20', updated_at=datetime('now')
WHERE key='raw_retention_days' AND value_json='7';

UPDATE app_settings
SET value_json='180', updated_at=datetime('now')
WHERE key='hourly_retention_days' AND value_json='90';
