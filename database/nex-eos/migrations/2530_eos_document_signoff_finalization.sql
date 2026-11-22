BEGIN;

CREATE TABLE IF NOT EXISTS eos_document_signoff_context (
    tenant_id VARCHAR(128) NOT NULL,
    case_id UUID NOT NULL,
    envelope_id UUID NOT NULL,
    approved_document_id VARCHAR(128) NOT NULL,
    document_revision INTEGER NOT NULL,
    document_type VARCHAR(64) NOT NULL,
    work_code VARCHAR(16) NOT NULL,
    document_content_hash VARCHAR(71) NOT NULL,
    attachment_manifest_hash VARCHAR(71) NOT NULL,
    approved_amount NUMERIC(20, 4) NOT NULL,
    approved_currency CHAR(3) NOT NULL,
    tolerance_policy_hash VARCHAR(71) NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ NULL,
    subject_hash VARCHAR(71) NOT NULL,
    document_payload_hash VARCHAR(71) NOT NULL,
    context_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_doc_signoff_context PRIMARY KEY (tenant_id, case_id),
    CONSTRAINT ux_eos_doc_signoff_context_envelope UNIQUE (
        tenant_id, envelope_id
    ),
    CONSTRAINT fk_eos_doc_signoff_context_case FOREIGN KEY (tenant_id, case_id)
        REFERENCES eos_scoped_approval_case (tenant_id, case_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_doc_signoff_revision CHECK (document_revision > 0),
    CONSTRAINT ck_eos_doc_signoff_amount CHECK (approved_amount > 0),
    CONSTRAINT ck_eos_doc_signoff_currency CHECK (
        approved_currency ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT ck_eos_doc_signoff_period CHECK (
        valid_until IS NULL OR valid_until > valid_from
    ),
    CONSTRAINT ck_eos_doc_signoff_hashes CHECK (
        document_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND attachment_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
        AND subject_hash ~ '^sha256:[0-9a-f]{64}$'
        AND document_payload_hash ~ '^sha256:[0-9a-f]{64}$'
        AND context_hash ~ '^sha256:[0-9a-f]{64}$'
        AND (
            tolerance_policy_hash IS NULL
            OR tolerance_policy_hash ~ '^sha256:[0-9a-f]{64}$'
        )
    )
);

CREATE TABLE IF NOT EXISTS eos_document_signoff_evidence (
    tenant_id VARCHAR(128) NOT NULL,
    case_id UUID NOT NULL,
    evidence_id UUID NOT NULL,
    company_id UUID NOT NULL,
    envelope_id UUID NOT NULL,
    context_hash VARCHAR(71) NOT NULL,
    document_payload_hash VARCHAR(71) NOT NULL,
    approver_subject_id VARCHAR(128) NOT NULL,
    approval_policy_hash VARCHAR(71) NOT NULL,
    wc_work_item_id UUID NOT NULL,
    wc_final_decision_id UUID NOT NULL,
    oa_authorization_revision_hash VARCHAR(71) NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    proof_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_doc_signoff_evidence PRIMARY KEY (tenant_id, case_id),
    CONSTRAINT ux_eos_doc_signoff_evidence UNIQUE (tenant_id, evidence_id),
    CONSTRAINT ux_eos_doc_signoff_envelope UNIQUE (tenant_id, envelope_id),
    CONSTRAINT fk_eos_doc_signoff_evidence_case FOREIGN KEY (tenant_id, case_id)
        REFERENCES eos_scoped_approval_case (tenant_id, case_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_doc_signoff_evidence_hashes CHECK (
        context_hash ~ '^sha256:[0-9a-f]{64}$'
        AND document_payload_hash ~ '^sha256:[0-9a-f]{64}$'
        AND approval_policy_hash ~ '^sha256:[0-9a-f]{64}$'
        AND oa_authorization_revision_hash ~ '^sha256:[0-9a-f]{64}$'
        AND proof_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

ALTER TABLE eos_approved_document_envelope
    ALTER COLUMN business_approval_proof_id DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS scoped_document_evidence_id UUID NULL;

ALTER TABLE eos_approved_document_envelope
    ADD CONSTRAINT ux_eos_approved_doc_scoped_evidence UNIQUE (
        tenant_id, scoped_document_evidence_id
    ),
    ADD CONSTRAINT fk_eos_approved_doc_scoped_evidence FOREIGN KEY (
        tenant_id, scoped_document_evidence_id
    ) REFERENCES eos_document_signoff_evidence (tenant_id, evidence_id),
    ADD CONSTRAINT ck_eos_approved_doc_proof_source CHECK (
        (
            business_approval_proof_id IS NOT NULL
            AND scoped_document_evidence_id IS NULL
        ) OR (
            business_approval_proof_id IS NULL
            AND scoped_document_evidence_id IS NOT NULL
        )
    );

CREATE OR REPLACE FUNCTION eos_reject_document_signoff_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Document signoff context and evidence are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_eos_doc_signoff_context_immutable
BEFORE UPDATE OR DELETE ON eos_document_signoff_context
FOR EACH ROW EXECUTE FUNCTION eos_reject_document_signoff_mutation();

CREATE TRIGGER trg_eos_doc_signoff_evidence_immutable
BEFORE UPDATE OR DELETE ON eos_document_signoff_evidence
FOR EACH ROW EXECUTE FUNCTION eos_reject_document_signoff_mutation();

CREATE OR REPLACE FUNCTION eos_guard_approved_doc_immutable()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ApprovedDocumentEnvelope cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF (to_jsonb(NEW) - 'state') IS DISTINCT FROM (to_jsonb(OLD) - 'state') THEN
        RAISE EXCEPTION 'ApprovedDocumentEnvelope content is immutable; create a new revision'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.state <> 'ACTIVE'
       OR NEW.state NOT IN ('REVOKED', 'EXPIRED', 'SUPERSEDED') THEN
        RAISE EXCEPTION 'ApprovedDocumentEnvelope state transition is invalid'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

INSERT INTO schema_migrations (version, description)
VALUES (
    '2530_eos_document_signoff_finalization',
    'Scoped document signoff context, evidence, and envelope proof compatibility'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
