BEGIN;

CREATE TABLE IF NOT EXISTS service_jobs (
    job_id TEXT PRIMARY KEY,
    job_schema_version TEXT NOT NULL DEFAULT 'common_job.v1'
        CHECK (job_schema_version = 'common_job.v1'),
    job_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
    trace_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 1 CHECK (max_attempts >= 1),
    retryable BOOLEAN NOT NULL DEFAULT TRUE,
    links JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    error JSONB,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at TIMESTAMPTZ,
    locked_by TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_service_jobs_attempts CHECK (attempt_count <= max_attempts),
    CONSTRAINT ux_service_jobs_idempotency UNIQUE (job_type, idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_service_jobs_status_available
    ON service_jobs (status, available_at);

CREATE INDEX IF NOT EXISTS ix_service_jobs_type_status
    ON service_jobs (job_type, status);

CREATE INDEX IF NOT EXISTS ix_service_jobs_trace
    ON service_jobs (trace_id);

CREATE INDEX IF NOT EXISTS ix_service_jobs_subject
    ON service_jobs (subject_type, subject_id);

INSERT INTO schema_migrations (version, description)
VALUES ('0083_service_job_queue_foundation', 'AE API service job queue foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
