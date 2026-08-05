BEGIN;

CREATE TABLE IF NOT EXISTS service_operational_events (
    event_id TEXT PRIMARY KEY,
    event_schema_version TEXT NOT NULL DEFAULT 'operational_event.v1'
        CHECK (event_schema_version = 'operational_event.v1'),
    service_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    trace_id TEXT,
    request_id TEXT,
    subject_type TEXT,
    subject_id TEXT,
    message TEXT NOT NULL CHECK (char_length(message) <= 512),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_service_operational_events_service_created
    ON service_operational_events (service_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_service_operational_events_severity_created
    ON service_operational_events (severity, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_service_operational_events_trace
    ON service_operational_events (trace_id);

CREATE INDEX IF NOT EXISTS ix_service_operational_events_type
    ON service_operational_events (event_type);

INSERT INTO schema_migrations (version, description)
VALUES ('0085_service_operational_events_foundation', 'OA service operational events foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
