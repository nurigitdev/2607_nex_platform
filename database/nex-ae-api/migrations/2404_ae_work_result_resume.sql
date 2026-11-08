BEGIN;

ALTER TABLE ae_wait_registration
    ADD COLUMN IF NOT EXISTS matched_event_id TEXT NULL,
    ADD COLUMN IF NOT EXISTS resume_runtime_job_id TEXT NULL,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NULL;

UPDATE ae_wait_registration
SET updated_at = COALESCE(updated_at, created_at)
WHERE updated_at IS NULL;

ALTER TABLE ae_wait_registration
    DROP CONSTRAINT IF EXISTS ck_ae_wait_match_lineage,
    ADD CONSTRAINT ck_ae_wait_match_lineage CHECK (
        (
            state IN ('PENDING', 'CANCELLED')
            AND matched_event_id IS NULL
            AND resume_runtime_job_id IS NULL
        )
        OR (
            state = 'SATISFIED'
            AND matched_event_id IS NOT NULL
            AND resume_runtime_job_id IS NULL
            AND satisfied_at IS NOT NULL
        )
        OR (
            state IN ('RESUME_QUEUED', 'CONSUMED')
            AND matched_event_id IS NOT NULL
            AND resume_runtime_job_id IS NOT NULL
            AND satisfied_at IS NOT NULL
        )
    );

CREATE TABLE IF NOT EXISTS ae_external_event_inbox (
    tenant_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type = 'WORK_RESULT_SUBMITTED'),
    event_semantic_hash TEXT NOT NULL
        CHECK (event_semantic_hash ~ '^sha256:[0-9a-f]{64}$'),
    external_ref TEXT NOT NULL,
    result_id TEXT NOT NULL,
    result_contract_ref TEXT NULL,
    event_payload JSONB NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('RECEIVED', 'MATCHED', 'REJECTED')),
    rejection_reason TEXT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ NULL,
    PRIMARY KEY (tenant_id, event_id),
    CONSTRAINT ck_ae_external_event_outcome CHECK (
        (state = 'RECEIVED' AND processed_at IS NULL AND rejection_reason IS NULL)
        OR (state = 'MATCHED' AND processed_at IS NOT NULL AND rejection_reason IS NULL)
        OR (state = 'REJECTED' AND processed_at IS NOT NULL
            AND rejection_reason IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_ae_event_inbox_pending
    ON ae_external_event_inbox (tenant_id, received_at, event_id)
    WHERE state = 'RECEIVED';

ALTER TABLE ae_runtime_job
    DROP CONSTRAINT IF EXISTS ae_runtime_job_job_type_check,
    DROP CONSTRAINT IF EXISTS ck_ae_runtime_job_type;

ALTER TABLE ae_runtime_job
    ADD CONSTRAINT ck_ae_runtime_job_type CHECK (job_type IN (
        'START_EXECUTION', 'CONTINUE_EXECUTION', 'RESUME_EXECUTION'
    ));

CREATE UNIQUE INDEX IF NOT EXISTS ux_ae_runtime_job_resume_wait
    ON ae_runtime_job (tenant_id, wait_id)
    WHERE job_type = 'RESUME_EXECUTION';

INSERT INTO schema_migrations (version, description)
VALUES (
    '2404_ae_work_result_resume',
    'AE WorkResult external event inbox and exactly-once resume scheduling'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
