BEGIN;

CREATE TABLE IF NOT EXISTS wc_work_result (
    tenant_id TEXT NOT NULL,
    result_id TEXT NOT NULL,
    work_item_id UUID NOT NULL,
    revision_no INTEGER NOT NULL CHECK (revision_no >= 1),
    result_type TEXT NOT NULL,
    result_schema_ref TEXT NOT NULL,
    result_hash TEXT NOT NULL CHECK (result_hash ~ '^sha256:[0-9a-f]{64}$'),
    result_payload JSONB NOT NULL,
    source_execution_ref TEXT NOT NULL,
    claim_id UUID NOT NULL,
    claim_generation INTEGER NOT NULL CHECK (claim_generation >= 1),
    assignment_id UUID NOT NULL,
    submitted_agent_id UUID NOT NULL,
    authorization_revision_hash TEXT NOT NULL,
    authorization_checked_at TIMESTAMPTZ NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, result_id),
    CONSTRAINT ux_wc_work_result_revision
        UNIQUE (tenant_id, work_item_id, revision_no),
    CONSTRAINT fk_wc_result_work FOREIGN KEY (tenant_id, work_item_id)
        REFERENCES wc_work_item (tenant_id, work_item_id),
    CONSTRAINT fk_wc_result_claim FOREIGN KEY (tenant_id, claim_id)
        REFERENCES wc_claim (tenant_id, claim_id),
    CONSTRAINT fk_wc_result_assignment FOREIGN KEY (tenant_id, assignment_id)
        REFERENCES wc_assignment (tenant_id, assignment_id)
);

CREATE INDEX IF NOT EXISTS ix_wc_result_work_submitted
    ON wc_work_result (tenant_id, work_item_id, submitted_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '1002_wc_work_result',
    'WC WorkResult atomic commit and WORK_RESULT_SUBMITTED outbox'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
