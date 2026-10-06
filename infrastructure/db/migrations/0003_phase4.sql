-- Phase 4: forecasts, evidence lineage, source health.
CREATE TABLE IF NOT EXISTS forecast_value (
    time TIMESTAMPTZ NOT NULL,
    event_id TEXT,
    origin_grid_id TEXT NOT NULL,
    grid_id TEXT NOT NULL,
    horizon_hours INTEGER NOT NULL,
    pm25 DOUBLE PRECISION NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    model_version TEXT NOT NULL,
    cams_applied BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (time, grid_id, horizon_hours, model_version)
);

SELECT create_hypertable('forecast_value', 'time', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS evidence_edge (
    edge_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    model_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_evidence_edge_event ON evidence_edge (event_id);

CREATE TABLE IF NOT EXISTS source_health (
    source_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'UNKNOWN',
    last_success_at TIMESTAMPTZ,
    last_record_at TIMESTAMPTZ,
    records_per_run INTEGER,
    error_rate DOUBLE PRECISION,
    quality_score DOUBLE PRECISION,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
