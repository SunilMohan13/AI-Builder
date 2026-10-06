-- Shadow serving (integration plan Phase 4).
--
-- Records a challenger's output next to what actually served, on the same
-- feature vector, so champion and challenger can be compared row by row after
-- a full seasonal window rather than on research data.
--
-- `feature_hash` is what makes the comparison trustworthy: it pins the exact
-- inputs both models saw, so a later analysis cannot silently compare rows
-- whose upstream observations were subsequently backfilled or corrected.
--
-- `error` is populated rather than the row being dropped. A challenger that
-- produced nothing for a month is a finding, and deleting those rows would
-- make a broken challenger indistinguishable from an unregistered one.

CREATE TABLE IF NOT EXISTS shadow_prediction (
    time TIMESTAMPTZ NOT NULL,
    grid_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    stage TEXT NOT NULL,
    shadow_value DOUBLE PRECISION,
    champion_value DOUBLE PRECISION,
    feature_hash TEXT NOT NULL,
    feature_completeness DOUBLE PRECISION,
    error TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (time, grid_id, model_name, model_version)
);

SELECT create_hypertable('shadow_prediction', 'time', if_not_exists => TRUE);

-- The comparison report scans one challenger version over a window.
CREATE INDEX IF NOT EXISTS idx_shadow_prediction_model
    ON shadow_prediction (model_name, model_version, time DESC);

-- Finding a broken challenger quickly matters more than the storage cost.
CREATE INDEX IF NOT EXISTS idx_shadow_prediction_errors
    ON shadow_prediction (model_name, time DESC)
    WHERE error IS NOT NULL;
