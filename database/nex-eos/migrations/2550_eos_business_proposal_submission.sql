BEGIN;

ALTER TABLE eos_business_proposal
    ADD COLUMN IF NOT EXISTS approval_preview_hash VARCHAR(71),
    ADD COLUMN IF NOT EXISTS candidate_evidence_hash VARCHAR(71),
    ADD COLUMN IF NOT EXISTS normalized_amount NUMERIC(20, 4),
    ADD COLUMN IF NOT EXISTS functional_currency VARCHAR(3),
    ADD COLUMN IF NOT EXISTS normalization_hash VARCHAR(71);

ALTER TABLE eos_business_proposal
    DROP CONSTRAINT IF EXISTS ck_eos_business_proposal_submission_binding;

ALTER TABLE eos_business_proposal
    ADD CONSTRAINT ck_eos_business_proposal_submission_binding CHECK (
        state NOT IN ('SUBMITTED', 'APPROVED', 'REJECTED')
        OR (
            submitted_revision_no IS NOT NULL
            AND approval_policy_id IS NOT NULL
            AND approval_policy_hash LIKE 'sha256:%'
            AND approval_preview_hash LIKE 'sha256:%'
            AND candidate_evidence_hash LIKE 'sha256:%'
            AND approval_line_hash LIKE 'sha256:%'
            AND normalized_amount > 0
            AND functional_currency ~ '^[A-Z]{3}$'
            AND normalization_hash LIKE 'sha256:%'
            AND submitted_at IS NOT NULL
        )
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2550_eos_business_proposal_submission',
    'Bind an exact approval preview and selected line to proposal submission'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
