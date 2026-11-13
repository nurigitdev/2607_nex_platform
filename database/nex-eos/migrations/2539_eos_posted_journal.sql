BEGIN;

ALTER TABLE eos_voucher_candidate
    ADD CONSTRAINT ux_eos_candidate_company_identity
    UNIQUE (tenant_id, company_id, candidate_id);

CREATE TABLE eos_accounting_approval_acceptance (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    acceptance_id UUID NOT NULL,
    candidate_id UUID NOT NULL,
    candidate_revision INTEGER NOT NULL,
    candidate_hash VARCHAR(71) NOT NULL,
    accounting_evidence_id UUID NOT NULL,
    approval_case_id UUID NOT NULL,
    purpose VARCHAR(32) NOT NULL,
    proof_hash VARCHAR(71) NOT NULL,
    wc_decision_id UUID NOT NULL,
    oa_decision_ref VARCHAR(256) NOT NULL,
    oa_decision_revision_hash VARCHAR(71) NOT NULL,
    accepted_by VARCHAR(128) NOT NULL,
    accepted_at TIMESTAMPTZ NOT NULL,
    journal_id UUID NOT NULL,
    acceptance_hash VARCHAR(71) NOT NULL,
    CONSTRAINT pk_eos_acct_acceptance PRIMARY KEY (
        tenant_id, company_id, acceptance_id
    ),
    CONSTRAINT ux_eos_acct_accept_candidate UNIQUE (
        tenant_id, company_id, candidate_id, candidate_revision
    ),
    CONSTRAINT ux_eos_acct_accept_proof UNIQUE (
        tenant_id, company_id, proof_hash
    ),
    CONSTRAINT ux_eos_acct_accept_journal UNIQUE (
        tenant_id, company_id, journal_id
    ),
    CONSTRAINT fk_eos_acct_accept_candidate FOREIGN KEY (
        tenant_id, candidate_id, candidate_revision
    ) REFERENCES eos_voucher_candidate_revision (
        tenant_id, candidate_id, revision_no
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_acct_accept_evidence FOREIGN KEY (
        tenant_id, accounting_evidence_id
    ) REFERENCES eos_accounting_approval_evidence (
        tenant_id, evidence_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_acct_accept_purpose CHECK (
        purpose = 'ACCOUNTING_POSTING'
    ),
    CONSTRAINT ck_eos_acct_accept_revision CHECK (
        candidate_revision > 0
    ),
    CONSTRAINT ck_eos_acct_accept_hashes CHECK (
        candidate_hash ~ '^sha256:[0-9a-f]{64}$'
        AND proof_hash ~ '^sha256:[0-9a-f]{64}$'
        AND oa_decision_revision_hash ~ '^sha256:[0-9a-f]{64}$'
        AND acceptance_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE TABLE eos_journal_header (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    journal_id UUID NOT NULL,
    candidate_id UUID NOT NULL,
    candidate_revision INTEGER NOT NULL,
    candidate_hash VARCHAR(71) NOT NULL,
    period_id UUID NOT NULL,
    posting_sequence BIGINT NOT NULL,
    journal_no VARCHAR(64) NOT NULL,
    state VARCHAR(16) NOT NULL,
    transaction_kind VARCHAR(16) NOT NULL,
    recognition_date DATE NOT NULL,
    posting_date DATE NOT NULL,
    functional_currency CHAR(3) NOT NULL,
    source_document_id UUID NOT NULL,
    source_document_revision INTEGER NOT NULL,
    source_document_hash VARCHAR(71) NOT NULL,
    accounting_acceptance_id UUID NOT NULL,
    posting_rule_release_hash VARCHAR(71) NOT NULL,
    fx_rate_set_hash VARCHAR(71) NOT NULL,
    reversal_of_journal_id UUID NULL,
    business_operation_id UUID NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    payload_hash VARCHAR(71) NOT NULL,
    line_count INTEGER NOT NULL,
    total_debit_functional NUMERIC(20,4) NOT NULL,
    total_credit_functional NUMERIC(20,4) NOT NULL,
    journal_hash VARCHAR(71) NOT NULL,
    posted_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_journal_header PRIMARY KEY (
        tenant_id, company_id, journal_id
    ),
    CONSTRAINT ux_eos_journal_candidate UNIQUE (
        tenant_id, company_id, candidate_id, candidate_revision
    ),
    CONSTRAINT ux_eos_journal_sequence UNIQUE (
        tenant_id, company_id, period_id, posting_sequence
    ),
    CONSTRAINT ux_eos_journal_no UNIQUE (
        tenant_id, company_id, journal_no
    ),
    CONSTRAINT ux_eos_journal_operation UNIQUE (
        tenant_id, business_operation_id
    ),
    CONSTRAINT ux_eos_journal_idempotency UNIQUE (
        tenant_id, company_id, idempotency_key
    ),
    CONSTRAINT ux_eos_journal_acceptance UNIQUE (
        tenant_id, company_id, accounting_acceptance_id
    ),
    CONSTRAINT fk_eos_journal_candidate FOREIGN KEY (
        tenant_id, candidate_id, candidate_revision
    ) REFERENCES eos_voucher_candidate_revision (
        tenant_id, candidate_id, revision_no
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_journal_period FOREIGN KEY (
        tenant_id, company_id, period_id
    ) REFERENCES eos_accounting_period (
        tenant_id, company_id, period_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_journal_document FOREIGN KEY (
        tenant_id, source_document_id
    ) REFERENCES eos_approved_document_envelope (
        tenant_id, envelope_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_journal_acceptance FOREIGN KEY (
        tenant_id, company_id, accounting_acceptance_id
    ) REFERENCES eos_accounting_approval_acceptance (
        tenant_id, company_id, acceptance_id
    ) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_eos_journal_reversal FOREIGN KEY (
        tenant_id, company_id, reversal_of_journal_id
    ) REFERENCES eos_journal_header (
        tenant_id, company_id, journal_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_journal_operation FOREIGN KEY (
        tenant_id, business_operation_id
    ) REFERENCES eos_business_operation (
        tenant_id, business_operation_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_journal_state CHECK (state = 'POSTED'),
    CONSTRAINT ck_eos_journal_kind CHECK (
        transaction_kind IN ('STANDARD', 'ADJUSTMENT', 'REVERSAL')
    ),
    CONSTRAINT ck_eos_journal_dates CHECK (
        posting_date >= recognition_date
    ),
    CONSTRAINT ck_eos_journal_currency CHECK (
        functional_currency ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT ck_eos_journal_counts CHECK (
        posting_sequence > 0
        AND candidate_revision > 0
        AND source_document_revision > 0
        AND line_count > 1
    ),
    CONSTRAINT ck_eos_journal_balanced CHECK (
        total_debit_functional > 0
        AND total_debit_functional = total_credit_functional
    ),
    CONSTRAINT ck_eos_journal_hashes CHECK (
        candidate_hash ~ '^sha256:[0-9a-f]{64}$'
        AND source_document_hash ~ '^sha256:[0-9a-f]{64}$'
        AND posting_rule_release_hash ~ '^sha256:[0-9a-f]{64}$'
        AND fx_rate_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND payload_hash ~ '^sha256:[0-9a-f]{64}$'
        AND journal_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

ALTER TABLE eos_accounting_approval_acceptance
    ADD CONSTRAINT fk_eos_acct_accept_journal FOREIGN KEY (
        tenant_id, company_id, journal_id
    ) REFERENCES eos_journal_header (
        tenant_id, company_id, journal_id
    ) DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE eos_journal_line (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    journal_id UUID NOT NULL,
    line_no INTEGER NOT NULL,
    candidate_id UUID NOT NULL,
    candidate_revision INTEGER NOT NULL,
    candidate_source_line_no INTEGER NOT NULL,
    account_id UUID NOT NULL,
    account_code_snapshot VARCHAR(64) NOT NULL,
    account_name_snapshot VARCHAR(256) NOT NULL,
    account_policy_id UUID NOT NULL,
    account_policy_release_hash VARCHAR(71) NOT NULL,
    posting_rule_release_hash VARCHAR(71) NOT NULL,
    project_id UUID NOT NULL,
    project_code VARCHAR(11) NOT NULL,
    debit_original NUMERIC(20,4) NOT NULL,
    credit_original NUMERIC(20,4) NOT NULL,
    original_currency CHAR(3) NOT NULL,
    debit_functional NUMERIC(20,4) NOT NULL,
    credit_functional NUMERIC(20,4) NOT NULL,
    functional_currency CHAR(3) NOT NULL,
    fx_rate_snapshot_id UUID NULL,
    fx_rate_snapshot_hash VARCHAR(71) NULL,
    source_record_line_ref VARCHAR(256) NOT NULL,
    description VARCHAR(1000) NULL,
    dimensions_json JSONB NOT NULL,
    evidence_hash VARCHAR(71) NOT NULL,
    line_hash VARCHAR(71) NOT NULL,
    CONSTRAINT pk_eos_journal_line PRIMARY KEY (
        tenant_id, company_id, journal_id, line_no
    ),
    CONSTRAINT ux_eos_journal_candidate_line UNIQUE (
        tenant_id, company_id, journal_id, candidate_source_line_no
    ),
    CONSTRAINT fk_eos_journal_line_header FOREIGN KEY (
        tenant_id, company_id, journal_id
    ) REFERENCES eos_journal_header (
        tenant_id, company_id, journal_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_journal_line_candidate FOREIGN KEY (
        tenant_id, candidate_id, candidate_revision, candidate_source_line_no
    ) REFERENCES eos_voucher_candidate_line (
        tenant_id, candidate_id, revision_no, line_no
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_journal_line_account FOREIGN KEY (
        tenant_id, account_id
    ) REFERENCES eos_account (tenant_id, account_id) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_journal_line_policy FOREIGN KEY (
        tenant_id, account_policy_id
    ) REFERENCES eos_company_account_policy (
        tenant_id, policy_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_journal_line_project FOREIGN KEY (
        tenant_id, project_id
    ) REFERENCES eos_project (tenant_id, project_id) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_journal_line_fx FOREIGN KEY (
        tenant_id, fx_rate_snapshot_id
    ) REFERENCES eos_fx_rate_snapshot (
        tenant_id, rate_snapshot_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_journal_line_numbers CHECK (
        line_no > 0 AND candidate_revision > 0 AND candidate_source_line_no > 0
    ),
    CONSTRAINT ck_eos_journal_line_sides CHECK (
        (
            debit_original > 0 AND credit_original = 0
            AND debit_functional > 0 AND credit_functional = 0
        ) OR (
            credit_original > 0 AND debit_original = 0
            AND credit_functional > 0 AND debit_functional = 0
        )
    ),
    CONSTRAINT ck_eos_journal_line_currencies CHECK (
        original_currency ~ '^[A-Z]{3}$'
        AND functional_currency ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT ck_eos_journal_line_project_code CHECK (
        project_code ~ '^[A-Z0-9]{4}[DMSOIG][0-9]{6}$'
    ),
    CONSTRAINT ck_eos_journal_line_dimensions CHECK (
        jsonb_typeof(dimensions_json) = 'object'
    ),
    CONSTRAINT ck_eos_journal_line_fx CHECK (
        (original_currency = functional_currency
            AND fx_rate_snapshot_id IS NULL
            AND fx_rate_snapshot_hash IS NULL)
        OR
        (original_currency <> functional_currency
            AND fx_rate_snapshot_id IS NOT NULL
            AND fx_rate_snapshot_hash ~ '^sha256:[0-9a-f]{64}$')
    ),
    CONSTRAINT ck_eos_journal_line_hashes CHECK (
        account_policy_release_hash ~ '^sha256:[0-9a-f]{64}$'
        AND posting_rule_release_hash ~ '^sha256:[0-9a-f]{64}$'
        AND evidence_hash ~ '^sha256:[0-9a-f]{64}$'
        AND line_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE INDEX ix_eos_journal_project_date
    ON eos_journal_line (tenant_id, company_id, project_id, journal_id);
CREATE INDEX ix_eos_journal_account
    ON eos_journal_line (tenant_id, company_id, account_id, journal_id);

CREATE TABLE eos_journal_sequence (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    period_id UUID NOT NULL,
    last_sequence BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_journal_sequence PRIMARY KEY (
        tenant_id, company_id, period_id
    ),
    CONSTRAINT fk_eos_journal_sequence_period FOREIGN KEY (
        tenant_id, company_id, period_id
    ) REFERENCES eos_accounting_period (
        tenant_id, company_id, period_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_journal_sequence_value CHECK (last_sequence > 0)
);

CREATE OR REPLACE FUNCTION eos_reject_posted_journal_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'PostedJournal and accounting acceptance are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_eos_acct_acceptance_immutable
BEFORE UPDATE OR DELETE ON eos_accounting_approval_acceptance
FOR EACH ROW EXECUTE FUNCTION eos_reject_posted_journal_mutation();

CREATE TRIGGER trg_eos_journal_header_immutable
BEFORE UPDATE OR DELETE ON eos_journal_header
FOR EACH ROW EXECUTE FUNCTION eos_reject_posted_journal_mutation();

CREATE TRIGGER trg_eos_journal_line_immutable
BEFORE UPDATE OR DELETE ON eos_journal_line
FOR EACH ROW EXECUTE FUNCTION eos_reject_posted_journal_mutation();

CREATE OR REPLACE FUNCTION eos_verify_posted_journal_balance()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    target_tenant VARCHAR(128);
    target_company UUID;
    target_journal UUID;
    expected_count INTEGER;
    expected_debit NUMERIC(20,4);
    expected_credit NUMERIC(20,4);
    actual_count INTEGER;
    actual_debit NUMERIC(20,4);
    actual_credit NUMERIC(20,4);
BEGIN
    target_tenant := COALESCE(NEW.tenant_id, OLD.tenant_id);
    target_company := COALESCE(NEW.company_id, OLD.company_id);
    target_journal := COALESCE(NEW.journal_id, OLD.journal_id);

    SELECT line_count, total_debit_functional, total_credit_functional
      INTO expected_count, expected_debit, expected_credit
      FROM eos_journal_header
     WHERE tenant_id = target_tenant
       AND company_id = target_company
       AND journal_id = target_journal;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    SELECT COUNT(*),
           COALESCE(SUM(debit_functional), 0),
           COALESCE(SUM(credit_functional), 0)
      INTO actual_count, actual_debit, actual_credit
      FROM eos_journal_line
     WHERE tenant_id = target_tenant
       AND company_id = target_company
       AND journal_id = target_journal;

    IF actual_count <> expected_count
       OR actual_debit <> expected_debit
       OR actual_credit <> expected_credit
       OR actual_debit <> actual_credit THEN
        RAISE EXCEPTION 'PostedJournal line count or functional balance mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER trg_eos_journal_header_balance
AFTER INSERT ON eos_journal_header
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION eos_verify_posted_journal_balance();

CREATE CONSTRAINT TRIGGER trg_eos_journal_line_balance
AFTER INSERT ON eos_journal_line
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION eos_verify_posted_journal_balance();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2539_eos_posted_journal',
    'Immutable PostedJournal, accounting acceptance, and balance protection'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
