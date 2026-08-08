BEGIN;

CREATE TABLE IF NOT EXISTS service_log_entries (
    log_id TEXT PRIMARY KEY,
    service_log_schema_version TEXT NOT NULL DEFAULT 'service_log_entry.v1'
        CHECK (service_log_schema_version = 'service_log_entry.v1'),
    service_id TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    logger_name TEXT NOT NULL CHECK (char_length(logger_name) <= 160),
    message TEXT NOT NULL CHECK (char_length(message) <= 512),
    trace_id TEXT,
    request_id TEXT,
    job_id TEXT,
    subject_type TEXT,
    subject_id TEXT,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    redacted_attribute_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
    observed_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_service_log_entries_service_observed
    ON service_log_entries (service_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS ix_service_log_entries_severity_observed
    ON service_log_entries (severity, observed_at DESC);

CREATE INDEX IF NOT EXISTS ix_service_log_entries_logger_observed
    ON service_log_entries (logger_name, observed_at DESC);

CREATE INDEX IF NOT EXISTS ix_service_log_entries_trace
    ON service_log_entries (trace_id);

CREATE INDEX IF NOT EXISTS ix_service_log_entries_request
    ON service_log_entries (request_id);

CREATE INDEX IF NOT EXISTS ix_service_log_entries_job
    ON service_log_entries (job_id);

CREATE INDEX IF NOT EXISTS ix_service_log_entries_subject
    ON service_log_entries (subject_type, subject_id);

INSERT INTO schema_migrations (version, description)
VALUES ('0137_service_log_entries_foundation', 'CX service log entries foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
