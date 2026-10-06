-- AeroPulse Phase 1 schema: source registry, checkpoints, observations, grid.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS data_source (
    source_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    data_type TEXT NOT NULL,
    endpoint TEXT,
    auth_ref TEXT,
    schedule TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    priority INTEGER NOT NULL DEFAULT 100,
    expected_interval_seconds INTEGER,
    last_success_at TIMESTAMPTZ,
    last_record_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'unknown',
    license TEXT,
    retention_policy TEXT,
    schema_version TEXT NOT NULL DEFAULT 'observation.v1'
);

CREATE TABLE IF NOT EXISTS connector_checkpoint (
    source_id TEXT PRIMARY KEY,
    cursor TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS connector_dead_letter (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    error TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS grid_cell (
    grid_id TEXT PRIMARY KEY,
    resolution INTEGER NOT NULL,
    center_lat DOUBLE PRECISION NOT NULL,
    center_lon DOUBLE PRECISION NOT NULL,
    geometry GEOMETRY(POLYGON, 4326),
    region_id TEXT,
    state TEXT,
    district TEXT,
    city TEXT
);

CREATE TABLE IF NOT EXISTS air_quality_observation (
    time TIMESTAMPTZ NOT NULL,
    observation_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    station_id TEXT,
    grid_id TEXT,
    parameter TEXT NOT NULL,
    value DOUBLE PRECISION,
    unit TEXT,
    quality_flag TEXT,
    quality_score DOUBLE PRECISION,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    raw_uri TEXT,
    dedup_key TEXT NOT NULL,
    PRIMARY KEY (time, observation_id)
);

CREATE TABLE IF NOT EXISTS weather_observation (
    time TIMESTAMPTZ NOT NULL,
    observation_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    grid_id TEXT,
    wind_u DOUBLE PRECISION,
    wind_v DOUBLE PRECISION,
    temperature DOUBLE PRECISION,
    humidity DOUBLE PRECISION,
    pressure DOUBLE PRECISION,
    boundary_layer_height DOUBLE PRECISION,
    quality_score DOUBLE PRECISION,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    raw_uri TEXT,
    dedup_key TEXT NOT NULL,
    PRIMARY KEY (time, observation_id)
);

CREATE TABLE IF NOT EXISTS fire_observation (
    time TIMESTAMPTZ NOT NULL,
    observation_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    grid_id TEXT,
    frp DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    sensor TEXT,
    quality_score DOUBLE PRECISION,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    raw_uri TEXT,
    dedup_key TEXT NOT NULL,
    PRIMARY KEY (time, observation_id)
);

SELECT create_hypertable('air_quality_observation', 'time', if_not_exists => TRUE);
SELECT create_hypertable('weather_observation', 'time', if_not_exists => TRUE);
SELECT create_hypertable('fire_observation', 'time', if_not_exists => TRUE);

CREATE UNIQUE INDEX IF NOT EXISTS uq_aq_dedup ON air_quality_observation (dedup_key, time);
CREATE UNIQUE INDEX IF NOT EXISTS uq_wx_dedup ON weather_observation (dedup_key, time);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fire_dedup ON fire_observation (dedup_key, time);

CREATE INDEX IF NOT EXISTS idx_aq_grid_time ON air_quality_observation (grid_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_fire_grid_time ON fire_observation (grid_id, time DESC);

INSERT INTO data_source (source_id, provider, connector_id, display_name, data_type, enabled, schema_version)
VALUES
    ('cpcb', 'CPCB', 'cpcb_caaqms', 'CPCB CAAQMS', 'air_quality', TRUE, 'observation.v1'),
    ('firms', 'NASA', 'firms_viirs', 'NASA FIRMS VIIRS', 'active_fire', TRUE, 'fire_observation.v1'),
    ('imd', 'IMD', 'imd_weather', 'IMD Weather', 'weather', TRUE, 'meteo.v1')
ON CONFLICT (source_id) DO NOTHING;
