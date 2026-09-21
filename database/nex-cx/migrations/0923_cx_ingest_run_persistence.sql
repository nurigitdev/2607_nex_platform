BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cx_ingest_runs (
    run_id UUID PRIMARY KEY,
    run_schema_version TEXT NOT NULL DEFAULT 'cx_ingest_run.v1'
        CHECK (run_schema_version = 'cx_ingest_run.v1'),
    document_id UUID NOT NULL REFERENCES cx_content_objects(content_object_id)
        ON DELETE CASCADE,
    job_id TEXT NOT NULL REFERENCES service_jobs(job_id),
    idempotency_key TEXT NOT NULL CHECK (char_length(idempotency_key) <= 256),
    status TEXT NOT NULL CHECK (
        status IN (
            'QUEUED',
            'RUNNING',
            'WAITING_RETRY',
            'SUCCEEDED',
            'FAILED',
            'CANCELLED'
        )
    ),
    current_step TEXT CHECK (
        current_step IS NULL OR current_step IN (
            'extraction',
            'chunking',
            'lexical_index',
            'embedding_index',
            'summary',
            'summary_embedding'
        )
    ),
    step_states JSONB NOT NULL DEFAULT '{}'::jsonb,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    checkpoint_version INTEGER NOT NULL DEFAULT 0 CHECK (checkpoint_version >= 0),
    tenant_ref_type TEXT NOT NULL DEFAULT 'oa.tenant'
        CHECK (tenant_ref_type = 'oa.tenant'),
    tenant_ref_id TEXT NOT NULL CHECK (
        tenant_ref_id <> '' AND char_length(tenant_ref_id) <= 128
    ),
    owner_subject_ref_type TEXT NOT NULL DEFAULT 'oa.user'
        CHECK (owner_subject_ref_type = 'oa.user'),
    owner_subject_ref_id TEXT NOT NULL CHECK (
        owner_subject_ref_id <> '' AND char_length(owner_subject_ref_id) <= 128
    ),
    trace_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    retry_at TIMESTAMPTZ,
    last_error JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    CONSTRAINT ux_cx_ingest_runs_owner_key UNIQUE (
        tenant_ref_id,
        owner_subject_ref_id,
        idempotency_key
    ),
    CONSTRAINT ck_cx_ingest_runs_attempts CHECK (attempt_count <= max_attempts),
    CONSTRAINT ck_cx_ingest_runs_lease CHECK (
        (status = 'RUNNING' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR (status <> 'RUNNING' AND lease_owner IS NULL AND lease_expires_at IS NULL)
    ),
    CONSTRAINT ck_cx_ingest_runs_retry CHECK (
        (status = 'WAITING_RETRY' AND retry_at IS NOT NULL)
        OR (status <> 'WAITING_RETRY' AND retry_at IS NULL)
    ),
    CONSTRAINT ck_cx_ingest_runs_completed CHECK (
        (status IN ('SUCCEEDED', 'FAILED', 'CANCELLED') AND completed_at IS NOT NULL)
        OR (status NOT IN ('SUCCEEDED', 'FAILED', 'CANCELLED') AND completed_at IS NULL)
    )
);

CREATE OR REPLACE FUNCTION cx_assert_ingest_run_owner()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    content_owner RECORD;
BEGIN
    SELECT
        tenant_ref_type,
        tenant_ref_id,
        owner_subject_ref_type,
        owner_subject_ref_id
    INTO STRICT content_owner
    FROM cx_content_objects
    WHERE content_object_id = NEW.document_id;

    IF NEW.tenant_ref_type <> content_owner.tenant_ref_type
       OR NEW.tenant_ref_id <> content_owner.tenant_ref_id
       OR NEW.owner_subject_ref_type <> content_owner.owner_subject_ref_type
       OR NEW.owner_subject_ref_id <> content_owner.owner_subject_ref_id THEN
        RAISE EXCEPTION 'CX ingestion run owner does not match document owner'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tr_cx_ingest_runs_owner ON cx_ingest_runs;
CREATE TRIGGER tr_cx_ingest_runs_owner
    BEFORE INSERT OR UPDATE OF
        document_id,
        tenant_ref_type,
        tenant_ref_id,
        owner_subject_ref_type,
        owner_subject_ref_id
    ON cx_ingest_runs
    FOR EACH ROW
    EXECUTE FUNCTION cx_assert_ingest_run_owner();

CREATE INDEX IF NOT EXISTS ix_cx_ingest_runs_status_retry
    ON cx_ingest_runs (status, retry_at, updated_at);

CREATE INDEX IF NOT EXISTS ix_cx_ingest_runs_lease
    ON cx_ingest_runs (status, lease_expires_at)
    WHERE status = 'RUNNING';

CREATE INDEX IF NOT EXISTS ix_cx_ingest_runs_owner_doc
    ON cx_ingest_runs (
        tenant_ref_id,
        owner_subject_ref_id,
        document_id,
        updated_at DESC
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '0923_cx_ingest_run_persistence',
    'CX durable ingestion run checkpoint and lease persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
