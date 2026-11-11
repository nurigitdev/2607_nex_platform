BEGIN;

CREATE TABLE IF NOT EXISTS eos_scoped_approval_case (
    tenant_id VARCHAR(128) NOT NULL,
    case_id UUID NOT NULL,
    idempotency_key VARCHAR(256) NOT NULL,
    company_id UUID NOT NULL,
    purpose VARCHAR(32) NOT NULL,
    scope_type VARCHAR(16) NOT NULL,
    project_set_hash VARCHAR(71) NOT NULL,
    subject_ref VARCHAR(256) NOT NULL,
    subject_revision INTEGER NOT NULL,
    subject_hash VARCHAR(71) NOT NULL,
    requester_ref_type VARCHAR(32) NOT NULL,
    requester_id VARCHAR(128) NOT NULL,
    approval_policy_id UUID NOT NULL,
    approval_policy_version INTEGER NOT NULL,
    approval_policy_hash VARCHAR(71) NOT NULL,
    oa_decision_ref VARCHAR(128) NOT NULL,
    authorization_revision_hash VARCHAR(71) NOT NULL,
    authorization_checked_at TIMESTAMPTZ NOT NULL,
    state VARCHAR(16) NOT NULL,
    active_stage_order INTEGER NULL,
    stage_count INTEGER NOT NULL,
    target_role_ref VARCHAR(32) NULL,
    version INTEGER NOT NULL,
    case_hash VARCHAR(71) NOT NULL,
    created_business_operation_id UUID NOT NULL,
    correlation_id VARCHAR(128) NOT NULL,
    causation_id VARCHAR(128) NOT NULL,
    expires_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    decided_at TIMESTAMPTZ NULL,
    CONSTRAINT pk_eos_scoped_approval PRIMARY KEY (tenant_id, case_id),
    CONSTRAINT ux_eos_scoped_approval_idem UNIQUE (
        tenant_id, idempotency_key
    ),
    CONSTRAINT ux_eos_scoped_approval_hash UNIQUE (tenant_id, case_hash),
    CONSTRAINT fk_eos_scoped_approval_company FOREIGN KEY (
        tenant_id, company_id
    ) REFERENCES eos_legal_entity (tenant_id, company_id),
    CONSTRAINT fk_eos_scoped_approval_policy FOREIGN KEY (
        tenant_id, approval_policy_id
    ) REFERENCES eos_approval_policy (tenant_id, approval_policy_id),
    CONSTRAINT fk_eos_scoped_approval_operation FOREIGN KEY (
        tenant_id, created_business_operation_id
    ) REFERENCES eos_business_operation (tenant_id, business_operation_id),
    CONSTRAINT ck_eos_scoped_approval_purpose CHECK (
        purpose IN ('DOCUMENT_SIGNOFF', 'ACCOUNTING_POSTING')
    ),
    CONSTRAINT ck_eos_scoped_approval_scope CHECK (
        scope_type IN ('COMPANY', 'PROJECT', 'PROJECT_SET')
    ),
    CONSTRAINT ck_eos_scoped_approval_state CHECK (
        state IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED', 'EXPIRED')
    ),
    CONSTRAINT ck_eos_scoped_approval_revision CHECK (subject_revision > 0),
    CONSTRAINT ck_eos_scoped_approval_stage_count CHECK (
        stage_count BETWEEN 1 AND 5
    ),
    CONSTRAINT ck_eos_scoped_approval_active_stage CHECK (
        active_stage_order IS NULL
        OR active_stage_order BETWEEN 1 AND stage_count
    ),
    CONSTRAINT ck_eos_scoped_approval_version CHECK (version > 0),
    CONSTRAINT ck_eos_scoped_approval_hashes CHECK (
        project_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND subject_hash ~ '^sha256:[0-9a-f]{64}$'
        AND approval_policy_hash ~ '^sha256:[0-9a-f]{64}$'
        AND authorization_revision_hash ~ '^sha256:[0-9a-f]{64}$'
        AND case_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_scoped_approval_period CHECK (
        expires_at IS NULL OR expires_at > created_at
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_eos_scoped_approval_subject
    ON eos_scoped_approval_case (
        tenant_id,
        company_id,
        purpose,
        subject_ref,
        subject_revision
    )
    WHERE state IN ('PENDING', 'APPROVED');

CREATE INDEX IF NOT EXISTS ix_eos_scoped_approval_state
    ON eos_scoped_approval_case (
        tenant_id, company_id, state, created_at
    );

CREATE TABLE IF NOT EXISTS eos_scoped_approval_subject_binding (
    tenant_id VARCHAR(128) NOT NULL,
    case_id UUID NOT NULL,
    project_id UUID NOT NULL,
    company_id UUID NOT NULL,
    authorization_scope_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_scoped_binding PRIMARY KEY (
        tenant_id, case_id, project_id
    ),
    CONSTRAINT ux_eos_scoped_binding_scope_hash UNIQUE (
        tenant_id, case_id, authorization_scope_hash
    ),
    CONSTRAINT fk_eos_scoped_binding_case FOREIGN KEY (
        tenant_id, case_id
    ) REFERENCES eos_scoped_approval_case (tenant_id, case_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_eos_scoped_binding_project FOREIGN KEY (
        tenant_id, project_id
    ) REFERENCES eos_project (tenant_id, project_id),
    CONSTRAINT fk_eos_scoped_binding_company FOREIGN KEY (
        tenant_id, company_id
    ) REFERENCES eos_legal_entity (tenant_id, company_id),
    CONSTRAINT ck_eos_scoped_binding_hash CHECK (
        authorization_scope_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_scoped_binding_project
    ON eos_scoped_approval_subject_binding (
        tenant_id, company_id, project_id
    );

CREATE OR REPLACE FUNCTION eos_guard_scoped_approval_case()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ScopedApprovalCase cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF ROW(
        NEW.tenant_id,
        NEW.case_id,
        NEW.idempotency_key,
        NEW.company_id,
        NEW.purpose,
        NEW.scope_type,
        NEW.project_set_hash,
        NEW.subject_ref,
        NEW.subject_revision,
        NEW.subject_hash,
        NEW.requester_ref_type,
        NEW.requester_id,
        NEW.approval_policy_id,
        NEW.approval_policy_version,
        NEW.approval_policy_hash,
        NEW.oa_decision_ref,
        NEW.authorization_revision_hash,
        NEW.authorization_checked_at,
        NEW.stage_count,
        NEW.case_hash,
        NEW.created_business_operation_id,
        NEW.correlation_id,
        NEW.causation_id,
        NEW.expires_at,
        NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.tenant_id,
        OLD.case_id,
        OLD.idempotency_key,
        OLD.company_id,
        OLD.purpose,
        OLD.scope_type,
        OLD.project_set_hash,
        OLD.subject_ref,
        OLD.subject_revision,
        OLD.subject_hash,
        OLD.requester_ref_type,
        OLD.requester_id,
        OLD.approval_policy_id,
        OLD.approval_policy_version,
        OLD.approval_policy_hash,
        OLD.oa_decision_ref,
        OLD.authorization_revision_hash,
        OLD.authorization_checked_at,
        OLD.stage_count,
        OLD.case_hash,
        OLD.created_business_operation_id,
        OLD.correlation_id,
        OLD.causation_id,
        OLD.expires_at,
        OLD.created_at
    ) THEN
        RAISE EXCEPTION 'ScopedApprovalCase material content is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.version <= OLD.version OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'ScopedApprovalCase workflow version must advance'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_eos_scoped_approval_case
BEFORE UPDATE OR DELETE ON eos_scoped_approval_case
FOR EACH ROW EXECUTE FUNCTION eos_guard_scoped_approval_case();

CREATE OR REPLACE FUNCTION eos_guard_scoped_approval_binding()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    parent_scope_type VARCHAR(16);
    parent_company_id UUID;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION 'ScopedApprovalSubjectBinding is immutable'
            USING ERRCODE = '55000';
    END IF;
    SELECT scope_type, company_id
      INTO parent_scope_type, parent_company_id
      FROM eos_scoped_approval_case
     WHERE tenant_id = NEW.tenant_id
       AND case_id = NEW.case_id;
    IF parent_scope_type = 'COMPANY' OR parent_company_id <> NEW.company_id THEN
        RAISE EXCEPTION 'Scoped approval Project binding does not match parent scope'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_eos_scoped_approval_binding
BEFORE INSERT OR UPDATE OR DELETE ON eos_scoped_approval_subject_binding
FOR EACH ROW EXECUTE FUNCTION eos_guard_scoped_approval_binding();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2527_eos_scoped_approval_case_v2',
    'Company and multi-Project scoped approval request persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
