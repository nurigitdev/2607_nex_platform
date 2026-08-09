BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cx_document_processing_runs (
    pipeline_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_schema_version TEXT NOT NULL DEFAULT 'cx_document_processing_pipeline.v1'
        CHECK (pipeline_schema_version = 'cx_document_processing_pipeline.v1'),
    document_id UUID NOT NULL REFERENCES cx_content_objects(content_object_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
    trace_id TEXT CHECK (trace_id IS NULL OR trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    job_id TEXT,
    job_type TEXT,
    job_status TEXT CHECK (
        job_status IS NULL
        OR job_status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')
    ),
    job_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (job_attempt_count >= 0),
    job_max_attempts INTEGER NOT NULL DEFAULT 0 CHECK (job_max_attempts >= 0),
    job_retryable BOOLEAN,
    job_subject_ref JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(job_subject_ref) = 'object'),
    job_links JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(job_links) = 'object'),
    step_total INTEGER NOT NULL DEFAULT 0 CHECK (step_total >= 0),
    step_succeeded INTEGER NOT NULL DEFAULT 0 CHECK (step_succeeded >= 0),
    step_skipped INTEGER NOT NULL DEFAULT 0 CHECK (step_skipped >= 0),
    step_failed INTEGER NOT NULL DEFAULT 0 CHECK (step_failed >= 0),
    queued_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_cx_processing_runs_step_total CHECK (
        step_total = step_succeeded + step_skipped + step_failed
    ),
    CONSTRAINT ck_cx_processing_runs_job_attempts CHECK (
        job_attempt_count <= job_max_attempts
        OR job_max_attempts = 0
    ),
    CONSTRAINT ck_cx_processing_runs_terminal_completed CHECK (
        status NOT IN ('SUCCEEDED', 'FAILED', 'CANCELLED')
        OR completed_at IS NOT NULL
    ),
    CONSTRAINT ck_cx_processing_runs_queued_started_order CHECK (
        queued_at IS NULL
        OR started_at IS NULL
        OR started_at >= queued_at
    ),
    CONSTRAINT ck_cx_processing_runs_completed_started_order CHECK (
        completed_at IS NULL
        OR started_at IS NULL
        OR completed_at >= started_at
    )
);

CREATE TABLE IF NOT EXISTS cx_document_processing_steps (
    pipeline_run_id UUID NOT NULL REFERENCES cx_document_processing_runs(pipeline_run_id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL CHECK (step_order > 0),
    step_id TEXT NOT NULL CHECK (step_id ~ '^[a-z][a-z0-9_]{0,63}$'),
    status TEXT NOT NULL CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'SKIPPED', 'FAILED')),
    output_ref_type TEXT,
    output_ref_id TEXT,
    output_ref_document_id UUID REFERENCES cx_content_objects(content_object_id) ON DELETE SET NULL,
    output_ref_hash TEXT CHECK (output_ref_hash IS NULL OR output_ref_hash ~ '^[0-9a-f]{64}$'),
    error_code TEXT,
    error_detail_sha256 TEXT CHECK (error_detail_sha256 IS NULL OR error_detail_sha256 ~ '^[0-9a-f]{64}$'),
    error_retryable BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (pipeline_run_id, step_order),
    UNIQUE (pipeline_run_id, step_id),
    CONSTRAINT ck_cx_processing_steps_success_output_ref CHECK (
        status NOT IN ('SUCCEEDED', 'SKIPPED')
        OR output_ref_hash IS NOT NULL
    ),
    CONSTRAINT ck_cx_processing_steps_failed_error CHECK (
        status <> 'FAILED'
        OR error_code IS NOT NULL
    ),
    CONSTRAINT ck_cx_processing_steps_nonfailed_error_hash CHECK (
        status = 'FAILED'
        OR (error_code IS NULL AND error_detail_sha256 IS NULL AND error_retryable IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_cx_processing_runs_document_updated
    ON cx_document_processing_runs (document_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_cx_processing_runs_status_updated
    ON cx_document_processing_runs (status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_cx_processing_runs_trace
    ON cx_document_processing_runs (trace_id);

CREATE INDEX IF NOT EXISTS idx_cx_processing_runs_job
    ON cx_document_processing_runs (job_id);

CREATE INDEX IF NOT EXISTS idx_cx_processing_steps_status
    ON cx_document_processing_steps (status, step_id);

CREATE INDEX IF NOT EXISTS idx_cx_processing_steps_output_ref
    ON cx_document_processing_steps (output_ref_type, output_ref_id);

CREATE INDEX IF NOT EXISTS idx_cx_processing_steps_document_ref
    ON cx_document_processing_steps (output_ref_document_id);

INSERT INTO schema_migrations (version, description)
VALUES ('0182_cx_processing_run_step_persistence', 'CX document processing run and step metadata persistence')
ON CONFLICT (version) DO NOTHING;

COMMIT;
