BEGIN;

CREATE TABLE IF NOT EXISTS eos_acct_approval_context (
    tenant_id VARCHAR(128) NOT NULL,
    case_id UUID NOT NULL,
    candidate_id UUID NOT NULL,
    candidate_revision INTEGER NOT NULL,
    candidate_hash VARCHAR(71) NOT NULL,
    document_envelope_hash VARCHAR(71) NOT NULL,
    fx_rate_set_hash VARCHAR(71) NOT NULL,
    rule_release_hash VARCHAR(71) NOT NULL,
    accounting_period_id UUID NOT NULL,
    candidate_preparer_id VARCHAR(128) NOT NULL,
    business_approver_ids JSONB NOT NULL,
    original_currency VARCHAR(3) NOT NULL,
    original_amount NUMERIC(24, 6) NOT NULL,
    market_base_rate NUMERIC(24, 10) NOT NULL,
    rate_reference_date DATE NOT NULL,
    rate_publication VARCHAR(256) NOT NULL,
    functional_currency VARCHAR(3) NOT NULL,
    functional_amount NUMERIC(24, 6) NOT NULL,
    fx_exception VARCHAR(512) NULL,
    review_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_acct_approval_context PRIMARY KEY (tenant_id, case_id),
    CONSTRAINT ux_eos_acct_context_candidate UNIQUE (
        tenant_id, candidate_id, candidate_revision
    ),
    CONSTRAINT fk_eos_acct_context_case FOREIGN KEY (tenant_id, case_id)
        REFERENCES eos_scoped_approval_case (tenant_id, case_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_acct_context_revision CHECK (candidate_revision > 0),
    CONSTRAINT ck_eos_acct_context_amounts CHECK (
        original_amount > 0 AND market_base_rate > 0 AND functional_amount > 0
    ),
    CONSTRAINT ck_eos_acct_context_hashes CHECK (
        candidate_hash ~ '^sha256:[0-9a-f]{64}$'
        AND document_envelope_hash ~ '^sha256:[0-9a-f]{64}$'
        AND fx_rate_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND rule_release_hash ~ '^sha256:[0-9a-f]{64}$'
        AND review_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_acct_context_approvers CHECK (
        jsonb_typeof(business_approver_ids) = 'array'
        AND jsonb_array_length(business_approver_ids) > 0
    )
);

CREATE TABLE IF NOT EXISTS eos_scoped_approval_decision (
    tenant_id VARCHAR(128) NOT NULL,
    case_id UUID NOT NULL,
    stage_order INTEGER NOT NULL,
    wc_work_item_id UUID NOT NULL,
    wc_decision_id UUID NOT NULL,
    wc_event_id UUID NOT NULL,
    wc_outbox_id UUID NOT NULL,
    decision VARCHAR(16) NOT NULL,
    decision_version INTEGER NOT NULL,
    decided_by VARCHAR(128) NOT NULL,
    decision_comment VARCHAR(2000) NULL,
    wc_oa_decision_ref VARCHAR(128) NOT NULL,
    wc_authorization_revision_hash VARCHAR(71) NOT NULL,
    oa_decision_ref VARCHAR(128) NOT NULL,
    authorization_revision_hash VARCHAR(71) NOT NULL,
    authorization_checked_at TIMESTAMPTZ NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    decision_hash VARCHAR(71) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_scoped_approval_decision PRIMARY KEY (
        tenant_id, case_id, stage_order
    ),
    CONSTRAINT ux_eos_scoped_decision_work_item UNIQUE (
        tenant_id, wc_work_item_id
    ),
    CONSTRAINT ux_eos_scoped_decision_decision UNIQUE (
        tenant_id, wc_decision_id
    ),
    CONSTRAINT ux_eos_scoped_decision_event UNIQUE (tenant_id, wc_event_id),
    CONSTRAINT fk_eos_scoped_decision_case FOREIGN KEY (tenant_id, case_id)
        REFERENCES eos_scoped_approval_case (tenant_id, case_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_scoped_decision_value CHECK (
        decision IN ('APPROVE', 'REJECT')
    ),
    CONSTRAINT ck_eos_scoped_decision_stage CHECK (stage_order > 0),
    CONSTRAINT ck_eos_scoped_decision_version CHECK (decision_version = 1),
    CONSTRAINT ck_eos_scoped_decision_hashes CHECK (
        wc_authorization_revision_hash ~ '^sha256:[0-9a-f]{64}$'
        AND authorization_revision_hash ~ '^sha256:[0-9a-f]{64}$'
        AND decision_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE TABLE IF NOT EXISTS eos_accounting_approval_evidence (
    tenant_id VARCHAR(128) NOT NULL,
    case_id UUID NOT NULL,
    evidence_id UUID NOT NULL,
    company_id UUID NOT NULL,
    candidate_id UUID NOT NULL,
    candidate_revision INTEGER NOT NULL,
    candidate_hash VARCHAR(71) NOT NULL,
    document_envelope_hash VARCHAR(71) NOT NULL,
    fx_rate_set_hash VARCHAR(71) NOT NULL,
    rule_release_hash VARCHAR(71) NOT NULL,
    accounting_period_id UUID NOT NULL,
    approver_subject_id VARCHAR(128) NOT NULL,
    approval_policy_hash VARCHAR(71) NOT NULL,
    wc_final_decision_id UUID NOT NULL,
    oa_authorization_revision_hash VARCHAR(71) NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    proof_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_accounting_approval_evidence PRIMARY KEY (
        tenant_id, case_id
    ),
    CONSTRAINT ux_eos_acct_evidence_id UNIQUE (tenant_id, evidence_id),
    CONSTRAINT ux_eos_acct_evidence_candidate UNIQUE (
        tenant_id, candidate_id, candidate_revision
    ),
    CONSTRAINT fk_eos_acct_evidence_case FOREIGN KEY (tenant_id, case_id)
        REFERENCES eos_scoped_approval_case (tenant_id, case_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_acct_evidence_hashes CHECK (
        candidate_hash ~ '^sha256:[0-9a-f]{64}$'
        AND document_envelope_hash ~ '^sha256:[0-9a-f]{64}$'
        AND fx_rate_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND rule_release_hash ~ '^sha256:[0-9a-f]{64}$'
        AND approval_policy_hash ~ '^sha256:[0-9a-f]{64}$'
        AND oa_authorization_revision_hash ~ '^sha256:[0-9a-f]{64}$'
        AND proof_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE OR REPLACE FUNCTION eos_reject_accounting_approval_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Accounting approval evidence is immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_eos_acct_context_immutable
BEFORE UPDATE OR DELETE ON eos_acct_approval_context
FOR EACH ROW EXECUTE FUNCTION eos_reject_accounting_approval_mutation();

CREATE TRIGGER trg_eos_scoped_decision_immutable
BEFORE UPDATE OR DELETE ON eos_scoped_approval_decision
FOR EACH ROW EXECUTE FUNCTION eos_reject_accounting_approval_mutation();

CREATE TRIGGER trg_eos_acct_evidence_immutable
BEFORE UPDATE OR DELETE ON eos_accounting_approval_evidence
FOR EACH ROW EXECUTE FUNCTION eos_reject_accounting_approval_mutation();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2528_eos_accounting_approval_human',
    'Human accounting SoD decision and immutable evidence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
