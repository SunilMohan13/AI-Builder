-- Issued forecast hours. These are not observations and do not feed detection.
CREATE TABLE IF NOT EXISTS meteo_forecast (
    source_id TEXT NOT NULL,
    forecast_id TEXT NOT NULL,
    valid_at TIMESTAMPTZ NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL,
    source_record_id TEXT NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    wind_u_10m DOUBLE PRECISION,
    wind_v_10m DOUBLE PRECISION,
    wind_u_100m DOUBLE PRECISION,
    wind_v_100m DOUBLE PRECISION,
    boundary_layer_height DOUBLE PRECISION,
    temperature DOUBLE PRECISION,
    humidity DOUBLE PRECISION,
    precipitation DOUBLE PRECISION,
    cams_pm25 DOUBLE PRECISION,
    grid_id TEXT,
    dedup_key TEXT,
    payload JSONB NOT NULL,
    PRIMARY KEY (source_id, forecast_id, valid_at)
);

SELECT create_hypertable('meteo_forecast', 'valid_at', if_not_exists => TRUE);
