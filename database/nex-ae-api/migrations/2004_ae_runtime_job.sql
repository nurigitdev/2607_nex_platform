BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_runtime_job (
    tenant_id TEXT NOT NULL,
    runtime_job_id TEXT NOT NULL,
    job_type TEXT NOT NULL CHECK (job_type IN (
        'START_EXECUTION', 'CONTINUE_EXECUTION'
    )),
    execution_id TEXT NOT NULL,
    executable_step_id TEXT NULL,
    wait_id TEXT NULL,
    reconciliation_id TEXT NULL,
    result_delivery_id TEXT NULL,
    publication_reconciliation_id TEXT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'QUEUED', 'RUNNING', 'DONE', 'FAILED', 'CANCELLED', 'DEAD_LETTER'
    )),
    dedup_key TEXT NOT NULL CHECK (char_length(dedup_key) > 0),
    attempt_no INTEGER NOT NULL DEFAULT 0 CHECK (attempt_no >= 0),
    run_after TIMESTAMPTZ NOT NULL,
    lease_owner TEXT NULL,
    lease_token TEXT NULL,
    lease_until TIMESTAMPTZ NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    correlation_id TEXT NOT NULL CHECK (char_length(correlation_id) > 0),
    causation_id TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, runtime_job_id),
    CONSTRAINT ux_ae_runtime_job_dedup UNIQUE (tenant_id, dedup_key),
    CONSTRAINT ck_ae_runtime_job_lease CHECK (
        state <> 'RUNNING'
        OR (
            lease_owner IS NOT NULL AND char_length(lease_owner) > 0
            AND lease_token IS NOT NULL AND char_length(lease_token) > 0
            AND lease_until IS NOT NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_ae_runtime_job_runnable
    ON ae_runtime_job (run_after, state)
    WHERE state = 'QUEUED';

CREATE INDEX IF NOT EXISTS idx_ae_runtime_job_lease
    ON ae_runtime_job (tenant_id, lease_until)
    WHERE state = 'RUNNING';

CREATE TABLE IF NOT EXISTS ae_runtime_job_attempt (
    attempt_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    runtime_job_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL CHECK (attempt_no >= 1),
    worker_id TEXT NOT NULL CHECK (char_length(worker_id) > 0),
    lease_token TEXT NOT NULL CHECK (char_length(lease_token) > 0),
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NULL,
    outcome TEXT NOT NULL CHECK (outcome IN (
        'RUNNING', 'DONE', 'FAILED', 'LEASE_EXPIRED', 'CANCELLED'
    )),
    error_ref TEXT NULL,
    retry_disposition_ref TEXT NULL,
    CONSTRAINT ux_ae_runtime_attempt_no
        UNIQUE (tenant_id, runtime_job_id, attempt_no)
);

CREATE INDEX IF NOT EXISTS idx_ae_runtime_attempt_job
    ON ae_runtime_job_attempt (tenant_id, runtime_job_id, attempt_no);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2004_ae_runtime_job',
    'Canonical Frozen RuntimeJob lease, retry, and attempt foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
