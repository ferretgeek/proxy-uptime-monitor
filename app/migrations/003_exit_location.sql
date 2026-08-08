ALTER TABLE nodes ADD COLUMN location_source TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE nodes ADD COLUMN location_checked_at TEXT;
ALTER TABLE nodes ADD COLUMN location_provider_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE nodes ADD COLUMN exit_ip_mask TEXT;

UPDATE nodes
SET location_source = CASE
    WHEN country_code IS NOT NULL AND country_code <> '' AND country_code <> 'ZZ'
        THEN 'name'
    ELSE 'unknown'
END;

CREATE INDEX IF NOT EXISTS idx_nodes_location_refresh
    ON nodes(enabled, source_present, location_source, location_checked_at);
