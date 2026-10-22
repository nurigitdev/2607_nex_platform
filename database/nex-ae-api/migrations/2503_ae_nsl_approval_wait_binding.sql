BEGIN;

ALTER TABLE ae_nsl_approval_request
    DROP CONSTRAINT IF EXISTS ux_ae_nsl_approval_request_lineage;

ALTER TABLE ae_nsl_approval_request
    ADD CONSTRAINT ux_ae_nsl_approval_request_lineage UNIQUE (
        tenant_id,
        approval_request_id,
        nsl_execution_id,
        business_operation_id
    );

ALTER TABLE ae_wait_registration
    ADD COLUMN IF NOT EXISTS nsl_execution_id TEXT NULL,
    ADD COLUMN IF NOT EXISTS business_operation_id TEXT NULL,
    ADD COLUMN IF NOT EXISTS approval_request_id TEXT NULL,
    ADD COLUMN IF NOT EXISTS checkpoint_version INTEGER NULL;

ALTER TABLE ae_wait_registration
    DROP CONSTRAINT IF EXISTS ck_ae_wait_nsl_approval_lineage,
    DROP CONSTRAINT IF EXISTS fk_ae_wait_nsl_approval_request;

ALTER TABLE ae_wait_registration
    ADD CONSTRAINT ck_ae_wait_nsl_approval_lineage CHECK (
        (
            wait_type = 'WORK_RESULT'
            AND nsl_execution_id IS NULL
            AND business_operation_id IS NULL
            AND approval_request_id IS NULL
            AND checkpoint_version IS NULL
        )
        OR
        (
            wait_type = 'NSL_APPROVAL'
            AND nsl_execution_id IS NOT NULL
            AND char_length(nsl_execution_id) BETWEEN 1 AND 256
            AND business_operation_id IS NOT NULL
            AND char_length(business_operation_id) BETWEEN 1 AND 256
            AND approval_request_id IS NOT NULL
            AND char_length(approval_request_id) BETWEEN 1 AND 256
            AND external_ref = approval_request_id
            AND checkpoint_version >= 1
        )
    ),
    ADD CONSTRAINT fk_ae_wait_nsl_approval_request FOREIGN KEY (
        tenant_id,
        approval_request_id,
        nsl_execution_id,
        business_operation_id
    ) REFERENCES ae_nsl_approval_request (
        tenant_id,
        approval_request_id,
        nsl_execution_id,
        business_operation_id
    );

CREATE INDEX IF NOT EXISTS ix_ae_wait_nsl_approval_pending
    ON ae_wait_registration (
        tenant_id,
        approval_request_id,
        nsl_execution_id,
        business_operation_id,
        checkpoint_version
    )
    WHERE wait_type = 'NSL_APPROVAL' AND state = 'PENDING';

INSERT INTO schema_migrations (version, description)
VALUES (
    '2503_ae_nsl_approval_wait_binding',
    'P8-S46 exact AE NSL approval wait lineage binding'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
