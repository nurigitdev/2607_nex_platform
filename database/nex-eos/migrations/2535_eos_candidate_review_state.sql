BEGIN;

ALTER TABLE eos_voucher_candidate
    DROP CONSTRAINT IF EXISTS ck_eos_candidate_s3_state;
ALTER TABLE eos_voucher_candidate
    ADD CONSTRAINT ck_eos_candidate_s3_state CHECK (
        state IN ('DRAFT', 'READY_FOR_REVIEW', 'RETURNED_FOR_CORRECTION')
    );

ALTER TABLE eos_acct_approval_context
    ADD COLUMN IF NOT EXISTS review_schema_version VARCHAR(64) NOT NULL
        DEFAULT 'eos_accounting_review_context.v2',
    ADD COLUMN IF NOT EXISTS candidate_version INTEGER NULL,
    ADD COLUMN IF NOT EXISTS validation_hash VARCHAR(71) NULL,
    ADD COLUMN IF NOT EXISTS validation_observed_at TIMESTAMPTZ NULL;

ALTER TABLE eos_acct_approval_context
    DROP CONSTRAINT IF EXISTS ck_eos_acct_context_s3;
ALTER TABLE eos_acct_approval_context
    ADD CONSTRAINT ck_eos_acct_context_s3 CHECK (
        (
            review_schema_version = 'eos_accounting_review_context.v2'
            AND candidate_version IS NULL
            AND validation_hash IS NULL
            AND validation_observed_at IS NULL
        )
        OR (
            review_schema_version = 'eos_accounting_review_context.v3'
            AND candidate_version > 0
            AND validation_hash ~ '^sha256:[0-9a-f]{64}$'
            AND validation_observed_at IS NOT NULL
        )
    );

CREATE TABLE IF NOT EXISTS eos_candidate_review_event (
    tenant_id VARCHAR(128) NOT NULL,
    event_id UUID NOT NULL,
    candidate_id UUID NOT NULL,
    candidate_revision INTEGER NOT NULL,
    candidate_hash VARCHAR(71) NOT NULL,
    approval_case_id UUID NOT NULL,
    transition_kind VARCHAR(16) NOT NULL,
    from_state VARCHAR(32) NOT NULL,
    to_state VARCHAR(32) NOT NULL,
    expected_version INTEGER NOT NULL,
    resulting_version INTEGER NOT NULL,
    actor_subject_id VARCHAR(128) NOT NULL,
    reason VARCHAR(2000) NULL,
    validation_hash VARCHAR(71) NULL,
    review_hash VARCHAR(71) NOT NULL,
    event_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_candidate_review_event PRIMARY KEY (tenant_id, event_id),
    CONSTRAINT ux_eos_candidate_review_version UNIQUE (
        tenant_id, candidate_id, resulting_version
    ),
    CONSTRAINT ux_eos_candidate_review_transition UNIQUE (
        tenant_id, approval_case_id, transition_kind
    ),
    CONSTRAINT fk_eos_candidate_review_candidate FOREIGN KEY (
        tenant_id, candidate_id
    ) REFERENCES eos_voucher_candidate (tenant_id, candidate_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_eos_candidate_review_case FOREIGN KEY (
        tenant_id, approval_case_id
    ) REFERENCES eos_scoped_approval_case (tenant_id, case_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_candidate_review_kind CHECK (
        transition_kind IN ('SUBMIT', 'RETURN', 'INVALIDATE')
    ),
    CONSTRAINT ck_eos_candidate_review_states CHECK (
        from_state IN ('DRAFT', 'READY_FOR_REVIEW', 'RETURNED_FOR_CORRECTION')
        AND to_state IN ('READY_FOR_REVIEW', 'RETURNED_FOR_CORRECTION')
    ),
    CONSTRAINT ck_eos_candidate_review_versions CHECK (
        candidate_revision > 0
        AND expected_version > 0
        AND resulting_version = expected_version + 1
    ),
    CONSTRAINT ck_eos_candidate_review_hashes CHECK (
        candidate_hash ~ '^sha256:[0-9a-f]{64}$'
        AND review_hash ~ '^sha256:[0-9a-f]{64}$'
        AND event_hash ~ '^sha256:[0-9a-f]{64}$'
        AND (
            validation_hash IS NULL
            OR validation_hash ~ '^sha256:[0-9a-f]{64}$'
        )
    ),
    CONSTRAINT ck_eos_candidate_review_reason CHECK (
        (transition_kind = 'SUBMIT' AND reason IS NULL AND validation_hash IS NOT NULL)
        OR (
            transition_kind IN ('RETURN', 'INVALIDATE')
            AND reason IS NOT NULL
            AND validation_hash IS NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_candidate_review_candidate
    ON eos_candidate_review_event (
        tenant_id, candidate_id, resulting_version DESC
    );

CREATE OR REPLACE FUNCTION eos_reject_candidate_review_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'VoucherCandidate review events are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_eos_candidate_review_immutable
BEFORE UPDATE OR DELETE ON eos_candidate_review_event
FOR EACH ROW EXECUTE FUNCTION eos_reject_candidate_review_mutation();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2535_eos_candidate_review_state',
    'VoucherCandidate review CAS state machine and immutable transition evidence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
