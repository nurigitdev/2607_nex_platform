BEGIN;

CREATE TABLE IF NOT EXISTS eos_voucher_candidate (
    tenant_id VARCHAR(128) NOT NULL,
    candidate_id UUID NOT NULL,
    company_id UUID NOT NULL,
    project_id UUID NOT NULL,
    project_code VARCHAR(11) NOT NULL,
    document_envelope_id UUID NOT NULL,
    preparer_subject_id VARCHAR(128) NOT NULL,
    source_kind VARCHAR(32) NOT NULL,
    source_record_ref VARCHAR(256) NOT NULL,
    business_work_code VARCHAR(16) NOT NULL,
    transaction_currency CHAR(3) NOT NULL,
    recognition_date DATE NOT NULL,
    state VARCHAR(32) NOT NULL,
    current_revision_no INTEGER NOT NULL,
    version INTEGER NOT NULL,
    created_business_operation_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_voucher_candidate PRIMARY KEY (tenant_id, candidate_id),
    CONSTRAINT ux_eos_candidate_operation UNIQUE (
        tenant_id, created_business_operation_id
    ),
    CONSTRAINT fk_eos_candidate_company FOREIGN KEY (tenant_id, company_id)
        REFERENCES eos_legal_entity (tenant_id, company_id),
    CONSTRAINT fk_eos_candidate_project FOREIGN KEY (tenant_id, project_id)
        REFERENCES eos_project (tenant_id, project_id),
    CONSTRAINT fk_eos_candidate_document FOREIGN KEY (
        tenant_id, document_envelope_id
    ) REFERENCES eos_approved_document_envelope (tenant_id, envelope_id),
    CONSTRAINT fk_eos_candidate_operation FOREIGN KEY (
        tenant_id, created_business_operation_id
    ) REFERENCES eos_business_operation (tenant_id, business_operation_id),
    CONSTRAINT ck_eos_candidate_project_code CHECK (
        project_code ~ '^[A-Z0-9]{4}[DMSOIG][0-9]{6}$'
    ),
    CONSTRAINT ck_eos_candidate_work_code CHECK (
        business_work_code ~ '^FL[0-9]{7}$'
    ),
    CONSTRAINT ck_eos_candidate_currency CHECK (
        transaction_currency ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT ck_eos_candidate_s3_state CHECK (state = 'DRAFT'),
    CONSTRAINT ck_eos_candidate_versions CHECK (
        current_revision_no > 0 AND version > 0
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_candidate_document
    ON eos_voucher_candidate (tenant_id, document_envelope_id);
CREATE INDEX IF NOT EXISTS ix_eos_candidate_project
    ON eos_voucher_candidate (tenant_id, project_id, state);

CREATE TABLE IF NOT EXISTS eos_voucher_candidate_revision (
    tenant_id VARCHAR(128) NOT NULL,
    candidate_id UUID NOT NULL,
    revision_no INTEGER NOT NULL,
    revision_id UUID NOT NULL,
    candidate_hash VARCHAR(71) NOT NULL,
    source_evidence_hash VARCHAR(71) NOT NULL,
    approved_document_hash VARCHAR(71) NOT NULL,
    attachment_manifest_hash VARCHAR(71) NOT NULL,
    fx_rate_set_hash VARCHAR(71) NULL,
    posting_rule_release_hash VARCHAR(71) NULL,
    account_policy_release_hash VARCHAR(71) NULL,
    journal_payload_hash VARCHAR(71) NULL,
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_candidate_revision PRIMARY KEY (
        tenant_id, candidate_id, revision_no
    ),
    CONSTRAINT ux_eos_candidate_revision_id UNIQUE (tenant_id, revision_id),
    CONSTRAINT fk_eos_candidate_revision FOREIGN KEY (
        tenant_id, candidate_id
    ) REFERENCES eos_voucher_candidate (tenant_id, candidate_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_candidate_revision_no CHECK (revision_no > 0),
    CONSTRAINT ck_eos_candidate_revision_hashes CHECK (
        candidate_hash ~ '^sha256:[0-9a-f]{64}$'
        AND source_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
        AND approved_document_hash ~ '^sha256:[0-9a-f]{64}$'
        AND attachment_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
        AND (
            fx_rate_set_hash IS NULL
            OR fx_rate_set_hash ~ '^sha256:[0-9a-f]{64}$'
        )
        AND (
            posting_rule_release_hash IS NULL
            OR posting_rule_release_hash ~ '^sha256:[0-9a-f]{64}$'
        )
        AND (
            account_policy_release_hash IS NULL
            OR account_policy_release_hash ~ '^sha256:[0-9a-f]{64}$'
        )
        AND (
            journal_payload_hash IS NULL
            OR journal_payload_hash ~ '^sha256:[0-9a-f]{64}$'
        )
    )
);

CREATE TABLE IF NOT EXISTS eos_voucher_candidate_line (
    tenant_id VARCHAR(128) NOT NULL,
    candidate_id UUID NOT NULL,
    revision_no INTEGER NOT NULL,
    line_no INTEGER NOT NULL,
    account_id UUID NOT NULL,
    project_id UUID NOT NULL,
    project_code VARCHAR(11) NOT NULL,
    debit_original NUMERIC(20, 4) NOT NULL,
    credit_original NUMERIC(20, 4) NOT NULL,
    original_currency CHAR(3) NOT NULL,
    source_record_line_ref VARCHAR(256) NOT NULL,
    description VARCHAR(1000) NULL,
    evidence_hash VARCHAR(71) NOT NULL,
    CONSTRAINT pk_eos_candidate_line PRIMARY KEY (
        tenant_id, candidate_id, revision_no, line_no
    ),
    CONSTRAINT fk_eos_candidate_line_revision FOREIGN KEY (
        tenant_id, candidate_id, revision_no
    ) REFERENCES eos_voucher_candidate_revision (
        tenant_id, candidate_id, revision_no
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_candidate_line_account FOREIGN KEY (
        tenant_id, account_id
    ) REFERENCES eos_account (tenant_id, account_id),
    CONSTRAINT fk_eos_candidate_line_project FOREIGN KEY (
        tenant_id, project_id
    ) REFERENCES eos_project (tenant_id, project_id),
    CONSTRAINT ck_eos_candidate_line_no CHECK (line_no > 0),
    CONSTRAINT ck_eos_candidate_line_side CHECK (
        (debit_original > 0 AND credit_original = 0)
        OR (credit_original > 0 AND debit_original = 0)
    ),
    CONSTRAINT ck_eos_candidate_line_project_code CHECK (
        project_code ~ '^[A-Z0-9]{4}[DMSOIG][0-9]{6}$'
    ),
    CONSTRAINT ck_eos_candidate_line_currency CHECK (
        original_currency ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT ck_eos_candidate_line_evidence CHECK (
        evidence_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE OR REPLACE FUNCTION eos_reject_candidate_revision_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'VoucherCandidate revisions and lines are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_eos_candidate_revision_immutable
BEFORE UPDATE OR DELETE ON eos_voucher_candidate_revision
FOR EACH ROW EXECUTE FUNCTION eos_reject_candidate_revision_mutation();

CREATE TRIGGER trg_eos_candidate_line_immutable
BEFORE UPDATE OR DELETE ON eos_voucher_candidate_line
FOR EACH ROW EXECUTE FUNCTION eos_reject_candidate_revision_mutation();

CREATE OR REPLACE FUNCTION eos_guard_candidate_identity()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'VoucherCandidate cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF (to_jsonb(NEW) - ARRAY[
        'state', 'current_revision_no', 'version', 'updated_at'
    ]) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY[
        'state', 'current_revision_no', 'version', 'updated_at'
    ]) THEN
        RAISE EXCEPTION 'VoucherCandidate identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_eos_candidate_identity_immutable
BEFORE UPDATE OR DELETE ON eos_voucher_candidate
FOR EACH ROW EXECUTE FUNCTION eos_guard_candidate_identity();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2534_eos_voucher_candidate_v2',
    'Proof-bound immutable VoucherCandidate v2 revision and line foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
