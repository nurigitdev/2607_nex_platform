BEGIN;

ALTER TABLE eos_scoped_approval_case
    ADD COLUMN IF NOT EXISTS target_approver_ref VARCHAR(128) NULL;

ALTER TABLE eos_business_proposal
    ADD COLUMN IF NOT EXISTS approval_line JSONB NULL;

CREATE TABLE IF NOT EXISTS eos_scoped_approval_nomination (
    tenant_id VARCHAR(128) NOT NULL,
    case_id UUID NOT NULL,
    stage_order INTEGER NOT NULL,
    position_type VARCHAR(32) NOT NULL,
    subject_id VARCHAR(128) NOT NULL,
    authority_hash VARCHAR(71) NOT NULL,
    approval_line_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_scoped_approval_nomination PRIMARY KEY (
        tenant_id, case_id, stage_order
    ),
    CONSTRAINT fk_eos_scoped_nomination_case FOREIGN KEY (
        tenant_id, case_id
    ) REFERENCES eos_scoped_approval_case (tenant_id, case_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_scoped_nomination_stage CHECK (
        stage_order BETWEEN 1 AND 5
    ),
    CONSTRAINT ck_eos_scoped_nomination_hashes CHECK (
        authority_hash ~ '^sha256:[0-9a-f]{64}$'
        AND approval_line_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE OR REPLACE FUNCTION eos_reject_scoped_approval_nomination_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Scoped approval nominations are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_eos_scoped_approval_nomination_immutable
BEFORE UPDATE OR DELETE ON eos_scoped_approval_nomination
FOR EACH ROW EXECUTE FUNCTION eos_reject_scoped_approval_nomination_mutation();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2551_eos_scoped_approval_nomination',
    'Bind requester-selected OA nominees to sequential scoped approval stages'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
