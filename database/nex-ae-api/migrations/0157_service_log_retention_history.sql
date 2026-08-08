BEGIN;

CREATE TABLE IF NOT EXISTS service_log_retention_history (
    execution_id TEXT PRIMARY KEY,
    retention_history_schema_version TEXT NOT NULL DEFAULT 'service_log_retention_history_entry.v1'
        CHECK (retention_history_schema_version = 'service_log_retention_history_entry.v1'),
    service_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('DRY_RUN', 'EXECUTE')),
    execution_status TEXT NOT NULL CHECK (execution_status IN ('PLANNED', 'SUCCEEDED', 'BLOCKED', 'FAILED')),
    delete_enabled BOOLEAN NOT NULL DEFAULT false,
    retention_days INTEGER NOT NULL CHECK (retention_days >= 7 AND retention_days <= 365),
    retention_cutoff TIMESTAMPTZ NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    candidate_count INTEGER NOT NULL CHECK (candidate_count >= 0),
    deleted_count INTEGER NOT NULL CHECK (deleted_count >= 0),
    requested_by JSONB NOT NULL DEFAULT '{}'::jsonb,
    idempotency_key TEXT,
    trace_id TEXT,
    request_id TEXT,
    blocked_reason TEXT,
    error JSONB,
    execution JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_service_log_retention_history_service_recorded
    ON service_log_retention_history (service_id, recorded_at DESC);

CREATE INDEX IF NOT EXISTS ix_service_log_retention_history_status_recorded
    ON service_log_retention_history (execution_status, recorded_at DESC);

CREATE INDEX IF NOT EXISTS ix_service_log_retention_history_mode_recorded
    ON service_log_retention_history (mode, recorded_at DESC);

CREATE INDEX IF NOT EXISTS ix_service_log_retention_history_trace
    ON service_log_retention_history (trace_id);

CREATE INDEX IF NOT EXISTS ix_service_log_retention_history_request
    ON service_log_retention_history (request_id);

CREATE INDEX IF NOT EXISTS ix_service_log_retention_history_idempotency
    ON service_log_retention_history (idempotency_key);

INSERT INTO schema_migrations (version, description)
VALUES ('0157_service_log_retention_history', 'AE API service log retention history foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
