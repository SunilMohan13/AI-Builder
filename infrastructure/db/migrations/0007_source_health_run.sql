-- Connector SourceRun persistence: latency, last error, and the mode the
-- runner actually resolved (live vs replay), not the requested banner.
ALTER TABLE source_health
    ADD COLUMN IF NOT EXISTS latency_ms INTEGER,
    ADD COLUMN IF NOT EXISTS last_error TEXT,
    ADD COLUMN IF NOT EXISTS processing_mode TEXT;
