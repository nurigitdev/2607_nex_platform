BEGIN;

CREATE TABLE IF NOT EXISTS eos_approved_document_envelope (
    tenant_id VARCHAR(128) NOT NULL,
    envelope_id UUID NOT NULL,
    company_id UUID NOT NULL,
    approved_document_id VARCHAR(128) NOT NULL,
    document_revision INTEGER NOT NULL,
    document_type VARCHAR(64) NOT NULL,
    work_code VARCHAR(16) NOT NULL,
    document_content_hash VARCHAR(71) NOT NULL,
    attachment_manifest_hash VARCHAR(71) NOT NULL,
    business_approval_proof_id UUID NOT NULL,
    business_proof_hash VARCHAR(71) NOT NULL,
    approval_policy_id UUID NOT NULL,
    approval_policy_version INTEGER NOT NULL,
    approval_policy_hash VARCHAR(71) NOT NULL,
    scope_type VARCHAR(16) NOT NULL,
    project_set_hash VARCHAR(71) NOT NULL,
    allowed_project_ids JSONB NOT NULL,
    approved_amount NUMERIC(20, 4) NOT NULL,
    approved_currency CHAR(3) NOT NULL,
    tolerance_policy_hash VARCHAR(71) NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ NULL,
    state VARCHAR(16) NOT NULL,
    approved_at TIMESTAMPTZ NOT NULL,
    approved_by_ref_type VARCHAR(32) NOT NULL,
    approved_by_id VARCHAR(128) NOT NULL,
    source_work_item_ref VARCHAR(256) NOT NULL,
    payload_hash VARCHAR(71) NOT NULL,
    created_business_operation_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_approved_doc PRIMARY KEY (tenant_id, envelope_id),
    CONSTRAINT ux_eos_approved_doc_revision UNIQUE (
        tenant_id, approved_document_id, document_revision
    ),
    CONSTRAINT ux_eos_approved_doc_proof UNIQUE (
        tenant_id, business_approval_proof_id
    ),
    CONSTRAINT fk_eos_approved_doc_company FOREIGN KEY (
        tenant_id, company_id
    ) REFERENCES eos_legal_entity (tenant_id, company_id),
    CONSTRAINT fk_eos_approved_doc_proof FOREIGN KEY (
        tenant_id, business_approval_proof_id
    ) REFERENCES eos_approval_proof (tenant_id, approval_proof_id),
    CONSTRAINT fk_eos_approved_doc_policy FOREIGN KEY (
        tenant_id, approval_policy_id
    ) REFERENCES eos_approval_policy (tenant_id, approval_policy_id),
    CONSTRAINT fk_eos_approved_doc_operation FOREIGN KEY (
        tenant_id, created_business_operation_id
    ) REFERENCES eos_business_operation (tenant_id, business_operation_id),
    CONSTRAINT ck_eos_approved_doc_revision CHECK (document_revision > 0),
    CONSTRAINT ck_eos_approved_doc_policy_version CHECK (
        approval_policy_version > 0
    ),
    CONSTRAINT ck_eos_approved_doc_amount CHECK (approved_amount > 0),
    CONSTRAINT ck_eos_approved_doc_currency CHECK (
        approved_currency ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT ck_eos_approved_doc_scope CHECK (
        scope_type IN ('COMPANY', 'PROJECT', 'PROJECT_SET')
    ),
    CONSTRAINT ck_eos_approved_doc_project_set CHECK (
        jsonb_typeof(allowed_project_ids) = 'array'
        AND (
            (scope_type = 'COMPANY' AND jsonb_array_length(allowed_project_ids) = 0)
            OR (scope_type = 'PROJECT' AND jsonb_array_length(allowed_project_ids) = 1)
            OR (scope_type = 'PROJECT_SET' AND jsonb_array_length(allowed_project_ids) >= 2)
        )
    ),
    CONSTRAINT ck_eos_approved_doc_state CHECK (
        state IN ('ACTIVE', 'REVOKED', 'EXPIRED', 'SUPERSEDED')
    ),
    CONSTRAINT ck_eos_approved_doc_period CHECK (
        valid_until IS NULL OR valid_until > valid_from
    ),
    CONSTRAINT ck_eos_approved_doc_hashes CHECK (
        document_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND attachment_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
        AND business_proof_hash ~ '^sha256:[0-9a-f]{64}$'
        AND approval_policy_hash ~ '^sha256:[0-9a-f]{64}$'
        AND project_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND payload_hash ~ '^sha256:[0-9a-f]{64}$'
        AND (
            tolerance_policy_hash IS NULL
            OR tolerance_policy_hash ~ '^sha256:[0-9a-f]{64}$'
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_approved_doc_lookup
    ON eos_approved_document_envelope (
        tenant_id, company_id, approved_document_id, document_revision
    );

CREATE INDEX IF NOT EXISTS ix_eos_approved_doc_validity
    ON eos_approved_document_envelope (
        tenant_id, state, valid_from, valid_until
    );

CREATE OR REPLACE FUNCTION eos_guard_approved_doc_immutable()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ApprovedDocumentEnvelope cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF ROW(
        NEW.tenant_id,
        NEW.envelope_id,
        NEW.company_id,
        NEW.approved_document_id,
        NEW.document_revision,
        NEW.document_type,
        NEW.work_code,
        NEW.document_content_hash,
        NEW.attachment_manifest_hash,
        NEW.business_approval_proof_id,
        NEW.business_proof_hash,
        NEW.approval_policy_id,
        NEW.approval_policy_version,
        NEW.approval_policy_hash,
        NEW.scope_type,
        NEW.project_set_hash,
        NEW.allowed_project_ids,
        NEW.approved_amount,
        NEW.approved_currency,
        NEW.tolerance_policy_hash,
        NEW.valid_from,
        NEW.valid_until,
        NEW.approved_at,
        NEW.approved_by_ref_type,
        NEW.approved_by_id,
        NEW.source_work_item_ref,
        NEW.payload_hash,
        NEW.created_business_operation_id,
        NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.tenant_id,
        OLD.envelope_id,
        OLD.company_id,
        OLD.approved_document_id,
        OLD.document_revision,
        OLD.document_type,
        OLD.work_code,
        OLD.document_content_hash,
        OLD.attachment_manifest_hash,
        OLD.business_approval_proof_id,
        OLD.business_proof_hash,
        OLD.approval_policy_id,
        OLD.approval_policy_version,
        OLD.approval_policy_hash,
        OLD.scope_type,
        OLD.project_set_hash,
        OLD.allowed_project_ids,
        OLD.approved_amount,
        OLD.approved_currency,
        OLD.tolerance_policy_hash,
        OLD.valid_from,
        OLD.valid_until,
        OLD.approved_at,
        OLD.approved_by_ref_type,
        OLD.approved_by_id,
        OLD.source_work_item_ref,
        OLD.payload_hash,
        OLD.created_business_operation_id,
        OLD.created_at
    ) THEN
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

CREATE TRIGGER trg_eos_approved_doc_immutable
BEFORE UPDATE OR DELETE ON eos_approved_document_envelope
FOR EACH ROW EXECUTE FUNCTION eos_guard_approved_doc_immutable();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2526_eos_approved_document_envelope',
    'Immutable approved document envelope bound to final business proof'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
