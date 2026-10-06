-- Persist satellite/raster metadata; large arrays remain in object storage.
CREATE TABLE IF NOT EXISTS raster_observation (
    acquisition_time TIMESTAMPTZ NOT NULL,
    observation_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    processing_time TIMESTAMPTZ NOT NULL,
    min_lon DOUBLE PRECISION NOT NULL,
    min_lat DOUBLE PRECISION NOT NULL,
    max_lon DOUBLE PRECISION NOT NULL,
    max_lat DOUBLE PRECISION NOT NULL,
    crs TEXT NOT NULL,
    resolution TEXT NOT NULL,
    object_uri TEXT NOT NULL,
    checksum TEXT NOT NULL,
    cloud_fraction DOUBLE PRECISION,
    quality_score DOUBLE PRECISION,
    sample_aod DOUBLE PRECISION,
    sample_no2 DOUBLE PRECISION,
    sample_pm25 DOUBLE PRECISION,
    payload JSONB NOT NULL,
    PRIMARY KEY (acquisition_time, observation_id)
);

SELECT create_hypertable('raster_observation', 'acquisition_time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_raster_source_time
    ON raster_observation (source_id, acquisition_time DESC);