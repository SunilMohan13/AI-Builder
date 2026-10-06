-- Phase 3: grid features, predictions, pollution events, evidence.
CREATE TABLE IF NOT EXISTS grid_feature (
    time TIMESTAMPTZ NOT NULL,
    grid_id TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    center_lat DOUBLE PRECISION,
    center_lon DOUBLE PRECISION,
    pm25 DOUBLE PRECISION,
    pm10 DOUBLE PRECISION,
    station_distance DOUBLE PRECISION,
    wind_u DOUBLE PRECISION,
    wind_v DOUBLE PRECISION,
    wind_speed DOUBLE PRECISION,
    wind_direction DOUBLE PRECISION,
    temperature DOUBLE PRECISION,
    humidity DOUBLE PRECISION,
    pressure DOUBLE PRECISION,
    boundary_layer_height DOUBLE PRECISION,
    fire_count INTEGER NOT NULL DEFAULT 0,
    fire_frp DOUBLE PRECISION NOT NULL DEFAULT 0,
    fire_confidence DOUBLE PRECISION,
    upwind_fire_score DOUBLE PRECISION,
    pm25_estimate DOUBLE PRECISION,
    estimate_confidence DOUBLE PRECISION,
    anomaly_score DOUBLE PRECISION,
    quality_score DOUBLE PRECISION,
    source_count INTEGER NOT NULL DEFAULT 0,
    missing_feature_count INTEGER NOT NULL DEFAULT 0,
    payload JSONB,
    PRIMARY KEY (time, grid_id)
);

SELECT create_hypertable('grid_feature', 'time', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS grid_prediction (
    time TIMESTAMPTZ NOT NULL,
    grid_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    pm25_estimate DOUBLE PRECISION NOT NULL,
    prediction_interval_low DOUBLE PRECISION,
    prediction_interval_high DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    PRIMARY KEY (time, grid_id, model_version)
);

SELECT create_hypertable('grid_prediction', 'time', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS pollution_event (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL DEFAULT 'pollution',
    status TEXT NOT NULL,
    severity TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    geometry TEXT,
    grid_ids TEXT[] NOT NULL DEFAULT '{}',
    pollutants TEXT[] NOT NULL DEFAULT ARRAY['PM2.5'],
    detection_confidence DOUBLE PRECISION NOT NULL,
    source_confidence DOUBLE PRECISION NOT NULL,
    forecast_confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    impact_confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    overall_confidence DOUBLE PRECISION NOT NULL,
    evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    model_versions TEXT[] NOT NULL DEFAULT '{}',
    feature_version TEXT,
    evidence_freshness DOUBLE PRECISION,
    sensor_coverage DOUBLE PRECISION,
    payload JSONB,
    CONSTRAINT pollution_event_status_chk CHECK (
        status IN (
            'DETECTED', 'VALIDATING', 'CONFIRMED', 'FORECASTING',
            'ACTIVE', 'DECLINING', 'RESOLVED', 'REJECTED'
        )
    )
);

CREATE TABLE IF NOT EXISTS event_evidence (
    evidence_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    observation_id TEXT,
    grid_id TEXT,
    summary TEXT NOT NULL,
    quality_score DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_event_status ON pollution_event (status);
CREATE INDEX IF NOT EXISTS idx_event_evidence_event ON event_evidence (event_id);
