BEGIN;

ALTER TABLE ae_external_event_inbox
    DROP CONSTRAINT IF EXISTS ae_external_event_inbox_event_type_check,
    DROP CONSTRAINT IF EXISTS ck_ae_external_event_type,
    DROP CONSTRAINT IF EXISTS ck_ae_external_event_shape;

ALTER TABLE ae_external_event_inbox
    ALTER COLUMN result_id DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS approval_request_id TEXT NULL,
    ADD COLUMN IF NOT EXISTS approval_work_item_ref TEXT NULL,
    ADD COLUMN IF NOT EXISTS approval_evidence_ref TEXT NULL,
    ADD COLUMN IF NOT EXISTS evidence_integrity TEXT NULL,
    ADD COLUMN IF NOT EXISTS nsl_execution_id TEXT NULL,
    ADD COLUMN IF NOT EXISTS business_operation_id TEXT NULL;

ALTER TABLE ae_external_event_inbox
    ADD CONSTRAINT ck_ae_external_event_type CHECK (
        event_type IN ('WORK_RESULT_SUBMITTED', 'NSL_APPROVAL_DECIDED')
    ),
    ADD CONSTRAINT ck_ae_external_event_shape CHECK (
        (
            event_type = 'WORK_RESULT_SUBMITTED'
            AND result_id IS NOT NULL
            AND approval_request_id IS NULL
            AND approval_work_item_ref IS NULL
            AND approval_evidence_ref IS NULL
            AND evidence_integrity IS NULL
            AND nsl_execution_id IS NULL
            AND business_operation_id IS NULL
        )
        OR
        (
            event_type = 'NSL_APPROVAL_DECIDED'
            AND result_id IS NULL
            AND result_contract_ref IS NULL
            AND approval_request_id IS NOT NULL
            AND char_length(approval_request_id) BETWEEN 1 AND 256
            AND external_ref = approval_request_id
            AND approval_work_item_ref IS NOT NULL
            AND char_length(approval_work_item_ref) BETWEEN 1 AND 128
            AND approval_evidence_ref IS NOT NULL
            AND char_length(approval_evidence_ref) BETWEEN 1 AND 512
            AND evidence_integrity ~ '^sha256:[0-9a-f]{64}$'
            AND nsl_execution_id IS NOT NULL
            AND char_length(nsl_execution_id) BETWEEN 1 AND 256
            AND business_operation_id IS NOT NULL
            AND char_length(business_operation_id) BETWEEN 1 AND 256
        )
    );

CREATE INDEX IF NOT EXISTS ix_ae_event_inbox_approval
    ON ae_external_event_inbox (
        tenant_id, approval_request_id, approval_work_item_ref, received_at
    )
    WHERE event_type = 'NSL_APPROVAL_DECIDED';

INSERT INTO schema_migrations (version, description)
VALUES (
    '2505_ae_nsl_approval_event_inbox',
    'P8-S50 typed NSL approval event inbox and bounded approval references'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
