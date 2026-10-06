-- Alerts raised from HIGH/CRITICAL pollution events (LLD section 29).
--
-- The event engine produced alerts into an in-process EventStore, which the
-- worker holds and the API never sees. GET /api/v1/alerts consequently
-- returned an empty list in every deployment, and the UI notification drawer
-- was permanently empty in Live. Persisting them is what closes that gap.

CREATE TABLE IF NOT EXISTS alert (
    alert_id          TEXT PRIMARY KEY,
    event_id          TEXT NOT NULL,
    severity          TEXT NOT NULL,
    recipient_group   TEXT NOT NULL DEFAULT 'operators',
    message_template  TEXT NOT NULL DEFAULT 'pollution_event',
    message           TEXT NOT NULL,
    evidence          JSONB NOT NULL DEFAULT '[]'::jsonb,
    channel           TEXT NOT NULL DEFAULT 'log',
    created_at        TIMESTAMPTZ NOT NULL,
    expires_at        TIMESTAMPTZ
);

-- The drawer and the alerts endpoint both read newest-first.
CREATE INDEX IF NOT EXISTS alert_created_at_idx ON alert (created_at DESC);

-- Looking up every alert raised for one event.
CREATE INDEX IF NOT EXISTS alert_event_id_idx ON alert (event_id);
