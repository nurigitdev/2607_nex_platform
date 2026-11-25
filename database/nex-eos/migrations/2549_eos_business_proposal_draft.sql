BEGIN;

CREATE TABLE IF NOT EXISTS eos_business_proposal (
    tenant_id VARCHAR(128) NOT NULL,
    proposal_id UUID NOT NULL,
    company_id UUID NOT NULL,
    requester_subject_id VARCHAR(128) NOT NULL,
    state VARCHAR(16) NOT NULL,
    current_revision_no INTEGER NOT NULL,
    version INTEGER NOT NULL,
    submitted_revision_no INTEGER NULL,
    approval_policy_id UUID NULL,
    approval_policy_hash VARCHAR(71) NULL,
    approval_line_hash VARCHAR(71) NULL,
    approval_case_id UUID NULL,
    approved_envelope_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    submitted_at TIMESTAMPTZ NULL,
    decided_at TIMESTAMPTZ NULL,
    withdrawn_at TIMESTAMPTZ NULL,
    CONSTRAINT pk_eos_business_proposal PRIMARY KEY (tenant_id, proposal_id),
    CONSTRAINT fk_eos_business_proposal_company FOREIGN KEY (
        tenant_id, company_id
    ) REFERENCES eos_legal_entity (tenant_id, company_id),
    CONSTRAINT ck_eos_business_proposal_state CHECK (
        state IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED', 'WITHDRAWN')
    ),
    CONSTRAINT ck_eos_business_proposal_versions CHECK (
        current_revision_no > 0 AND version > 0
    ),
    CONSTRAINT ck_eos_business_proposal_hashes CHECK (
        (approval_policy_hash IS NULL OR approval_policy_hash ~ '^sha256:[0-9a-f]{64}$')
        AND (approval_line_hash IS NULL OR approval_line_hash ~ '^sha256:[0-9a-f]{64}$')
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_business_proposal_owner
    ON eos_business_proposal (
        tenant_id, requester_subject_id, state, updated_at
    );

CREATE TABLE IF NOT EXISTS eos_business_proposal_revision (
    tenant_id VARCHAR(128) NOT NULL,
    proposal_id UUID NOT NULL,
    revision_no INTEGER NOT NULL,
    revision_id UUID NOT NULL,
    predecessor_revision_no INTEGER NULL,
    document_type VARCHAR(64) NOT NULL,
    work_code VARCHAR(16) NOT NULL,
    title VARCHAR(300) NOT NULL,
    purpose TEXT NOT NULL,
    business_justification TEXT NOT NULL,
    transaction_type VARCHAR(64) NOT NULL,
    requested_amount NUMERIC(20, 4) NOT NULL,
    original_currency CHAR(3) NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ NULL,
    scope_type VARCHAR(16) NOT NULL,
    project_ids JSONB NOT NULL,
    project_codes JSONB NOT NULL,
    attachment_manifest JSONB NOT NULL,
    content_hash VARCHAR(71) NOT NULL,
    attachment_manifest_hash VARCHAR(71) NOT NULL,
    policy_selection_input_hash VARCHAR(71) NOT NULL,
    created_by_subject_id VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_business_proposal_revision PRIMARY KEY (
        tenant_id, proposal_id, revision_no
    ),
    CONSTRAINT ux_eos_business_proposal_revision_id UNIQUE (
        tenant_id, revision_id
    ),
    CONSTRAINT ux_eos_business_proposal_content UNIQUE (
        tenant_id, proposal_id, content_hash
    ),
    CONSTRAINT fk_eos_business_proposal_revision FOREIGN KEY (
        tenant_id, proposal_id
    ) REFERENCES eos_business_proposal (tenant_id, proposal_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_business_proposal_revision CHECK (revision_no > 0),
    CONSTRAINT ck_eos_business_proposal_predecessor CHECK (
        predecessor_revision_no IS NULL OR predecessor_revision_no > 0
    ),
    CONSTRAINT ck_eos_business_proposal_amount CHECK (requested_amount > 0),
    CONSTRAINT ck_eos_business_proposal_currency CHECK (
        original_currency ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT ck_eos_business_proposal_scope CHECK (
        scope_type IN ('COMPANY', 'PROJECT', 'PROJECT_SET')
    ),
    CONSTRAINT ck_eos_business_proposal_project_scope CHECK (
        jsonb_typeof(project_ids) = 'array'
        AND jsonb_typeof(project_codes) = 'array'
        AND jsonb_array_length(project_ids) = jsonb_array_length(project_codes)
        AND (
            (scope_type = 'COMPANY' AND jsonb_array_length(project_ids) = 0)
            OR (scope_type = 'PROJECT' AND jsonb_array_length(project_ids) = 1)
            OR (scope_type = 'PROJECT_SET' AND jsonb_array_length(project_ids) >= 2)
        )
    ),
    CONSTRAINT ck_eos_business_proposal_hashes CHECK (
        content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND attachment_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
        AND policy_selection_input_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_business_proposal_validity CHECK (
        valid_until IS NULL OR valid_until > valid_from
    )
);

CREATE OR REPLACE FUNCTION eos_reject_business_proposal_revision_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Business proposal revisions are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_eos_business_proposal_revision_immutable
BEFORE UPDATE OR DELETE ON eos_business_proposal_revision
FOR EACH ROW EXECUTE FUNCTION eos_reject_business_proposal_revision_mutation();

CREATE OR REPLACE FUNCTION eos_guard_business_proposal_identity()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Business proposal cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF ROW(NEW.tenant_id, NEW.proposal_id, NEW.company_id,
           NEW.requester_subject_id, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.tenant_id, OLD.proposal_id, OLD.company_id,
           OLD.requester_subject_id, OLD.created_at) THEN
        RAISE EXCEPTION 'Business proposal identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_eos_business_proposal_identity_immutable
BEFORE UPDATE OR DELETE ON eos_business_proposal
FOR EACH ROW EXECUTE FUNCTION eos_guard_business_proposal_identity();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2549_eos_business_proposal_draft',
    'Durable business proposal aggregate and immutable revision foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
