BEGIN;

CREATE TABLE IF NOT EXISTS eos_project_code_counter (
    tenant_id VARCHAR(128) NOT NULL,
    tenant_code CHAR(4) NOT NULL,
    code_kind VARCHAR(16) NOT NULL,
    purpose_type CHAR(1) NOT NULL,
    code_year INTEGER NOT NULL,
    last_serial INTEGER NOT NULL,
    version INTEGER NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_project_code_counter PRIMARY KEY (
        tenant_id, code_kind, purpose_type, code_year
    ),
    CONSTRAINT ck_eos_project_counter_tenant_identity CHECK (
        tenant_id = tenant_code
    ),
    CONSTRAINT ck_eos_project_counter_tenant_code CHECK (
        tenant_code ~ '^[A-Z0-9]{4}$'
    ),
    CONSTRAINT ck_eos_project_counter_kind CHECK (
        code_kind IN ('REQUEST', 'REGISTRATION')
    ),
    CONSTRAINT ck_eos_project_counter_purpose CHECK (
        (code_kind = 'REQUEST' AND purpose_type = 'R')
        OR
        (code_kind = 'REGISTRATION' AND purpose_type IN ('D', 'M', 'S', 'O', 'I', 'G'))
    ),
    CONSTRAINT ck_eos_project_counter_year CHECK (code_year BETWEEN 0 AND 99),
    CONSTRAINT ck_eos_project_counter_serial CHECK (last_serial BETWEEN 1 AND 9999),
    CONSTRAINT ck_eos_project_counter_version CHECK (version > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_eos_project_counter_code_scope
    ON eos_project_code_counter (
        tenant_code, code_kind, purpose_type, code_year
    );

CREATE TABLE IF NOT EXISTS eos_project_application (
    tenant_id VARCHAR(128) NOT NULL,
    application_id UUID NOT NULL,
    tenant_code CHAR(4) NOT NULL,
    code_year INTEGER NOT NULL,
    project_request_code CHAR(11) NOT NULL,
    purpose_type CHAR(1) NOT NULL,
    state VARCHAR(16) NOT NULL,
    applicant_subject_id VARCHAR(128) NOT NULL,
    current_revision INTEGER NOT NULL,
    approved_project_id UUID NULL,
    approved_project_code VARCHAR(64) NULL,
    version INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    submitted_at TIMESTAMPTZ NULL,
    decided_at TIMESTAMPTZ NULL,
    CONSTRAINT pk_eos_project_application PRIMARY KEY (tenant_id, application_id),
    CONSTRAINT ux_eos_project_application_request UNIQUE (
        tenant_id, project_request_code
    ),
    CONSTRAINT ux_eos_project_application_code_global UNIQUE (
        project_request_code
    ),
    CONSTRAINT ck_eos_project_application_tenant_code CHECK (
        tenant_code ~ '^[A-Z0-9]{4}$' AND tenant_id = tenant_code
    ),
    CONSTRAINT ck_eos_project_application_request_code CHECK (
        project_request_code = tenant_code || 'R'
            || to_char(code_year, 'FM00')
            || substring(project_request_code FROM 8 FOR 4)
        AND project_request_code ~ '^[A-Z0-9]{4}R[0-9]{6}$'
        AND substring(project_request_code FROM 8 FOR 4)::INTEGER BETWEEN 1 AND 9999
    ),
    CONSTRAINT ck_eos_project_application_year CHECK (
        code_year BETWEEN 0 AND 99
    ),
    CONSTRAINT ck_eos_project_application_purpose CHECK (
        purpose_type IN ('D', 'M', 'S', 'O', 'I', 'G')
    ),
    CONSTRAINT ck_eos_project_application_state CHECK (
        state IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED')
    ),
    CONSTRAINT ck_eos_project_application_revision CHECK (current_revision > 0),
    CONSTRAINT ck_eos_project_application_version CHECK (version > 0),
    CONSTRAINT ck_eos_project_application_times CHECK (
        (state = 'DRAFT' AND submitted_at IS NULL AND decided_at IS NULL)
        OR
        (state = 'SUBMITTED' AND submitted_at IS NOT NULL AND decided_at IS NULL)
        OR
        (state IN ('APPROVED', 'REJECTED') AND submitted_at IS NOT NULL AND decided_at IS NOT NULL)
    ),
    CONSTRAINT ck_eos_project_application_approval_binding CHECK (
        (state = 'APPROVED' AND approved_project_id IS NOT NULL AND approved_project_code IS NOT NULL)
        OR
        (state <> 'APPROVED' AND approved_project_id IS NULL AND approved_project_code IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_project_application_state
    ON eos_project_application (tenant_id, state, updated_at, application_id);

CREATE TABLE IF NOT EXISTS eos_project_app_revision (
    tenant_id VARCHAR(128) NOT NULL,
    application_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    request_hash VARCHAR(71) NOT NULL,
    payload_json TEXT NOT NULL,
    created_by_subject_id VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_project_app_revision PRIMARY KEY (
        tenant_id, application_id, revision
    ),
    CONSTRAINT ux_eos_project_app_revision_hash UNIQUE (
        tenant_id, application_id, request_hash
    ),
    CONSTRAINT fk_eos_project_app_revision FOREIGN KEY (
        tenant_id, application_id
    ) REFERENCES eos_project_application (tenant_id, application_id),
    CONSTRAINT ck_eos_project_app_revision_number CHECK (revision > 0),
    CONSTRAINT ck_eos_project_app_revision_hash CHECK (
        request_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE OR REPLACE FUNCTION eos_guard_project_app_revision_immutable()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Project application revisions are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_eos_project_app_revision_immutable
BEFORE UPDATE OR DELETE ON eos_project_app_revision
FOR EACH ROW EXECUTE FUNCTION eos_guard_project_app_revision_immutable();

CREATE OR REPLACE FUNCTION eos_guard_project_application_lifecycle()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.project_request_code IS DISTINCT FROM OLD.project_request_code
       OR NEW.tenant_code IS DISTINCT FROM OLD.tenant_code
       OR NEW.code_year IS DISTINCT FROM OLD.code_year
       OR NEW.applicant_subject_id IS DISTINCT FROM OLD.applicant_subject_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'Project application identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.state <> OLD.state AND NOT (
        (OLD.state = 'DRAFT' AND NEW.state = 'SUBMITTED')
        OR
        (OLD.state = 'SUBMITTED' AND NEW.state IN ('APPROVED', 'REJECTED'))
    ) THEN
        RAISE EXCEPTION 'Project application state transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.current_revision <> OLD.current_revision
       AND (
           OLD.state <> 'DRAFT'
           OR NEW.state <> 'DRAFT'
           OR NEW.current_revision <> OLD.current_revision + 1
       ) THEN
        RAISE EXCEPTION 'Project application revision transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'Project application version must advance by one'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_eos_project_application_lifecycle
BEFORE UPDATE ON eos_project_application
FOR EACH ROW EXECUTE FUNCTION eos_guard_project_application_lifecycle();

ALTER TABLE eos_project
    ADD COLUMN IF NOT EXISTS project_request_code CHAR(11) NULL,
    ADD COLUMN IF NOT EXISTS purpose_type CHAR(1) NULL,
    ADD COLUMN IF NOT EXISTS origin VARCHAR(32) NOT NULL DEFAULT 'LEGACY_DIRECT',
    ADD COLUMN IF NOT EXISTS approval_evidence_ref VARCHAR(256) NULL,
    ADD COLUMN IF NOT EXISTS approval_evidence_hash VARCHAR(71) NULL,
    ADD COLUMN IF NOT EXISTS agent_sync_state VARCHAR(16) NOT NULL DEFAULT 'IN_SYNC';

ALTER TABLE eos_project
    DROP CONSTRAINT IF EXISTS ck_eos_project_status;

ALTER TABLE eos_project
    ADD CONSTRAINT ck_eos_project_status CHECK (
        status IN ('ACTIVE', 'INACTIVE', 'CLOSING', 'CLOSED')
    ),
    ADD CONSTRAINT ux_eos_project_request_code UNIQUE (
        tenant_id, project_request_code
    ),
    ADD CONSTRAINT ck_eos_project_origin CHECK (
        origin IN ('LEGACY_DIRECT', 'APPROVED_APPLICATION')
    ),
    ADD CONSTRAINT ck_eos_project_purpose CHECK (
        purpose_type IS NULL OR purpose_type IN ('D', 'M', 'S', 'O', 'I', 'G')
    ),
    ADD CONSTRAINT ck_eos_project_agent_sync CHECK (
        agent_sync_state IN ('PENDING', 'IN_SYNC', 'FAILED')
    ),
    ADD CONSTRAINT ck_eos_project_application_lineage CHECK (
        (
            origin = 'LEGACY_DIRECT'
            AND project_request_code IS NULL
            AND purpose_type IS NULL
        ) OR (
            origin = 'APPROVED_APPLICATION'
            AND project_request_code ~ '^[A-Z0-9]{4}R[0-9]{6}$'
            AND purpose_type IN ('D', 'M', 'S', 'O', 'I', 'G')
            AND project_code ~ ('^[A-Z0-9]{4}' || purpose_type || '[0-9]{6}$')
            AND approval_evidence_ref IS NOT NULL
            AND approval_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
        )
    );

CREATE UNIQUE INDEX IF NOT EXISTS ux_eos_project_request_code_global
    ON eos_project (project_request_code)
    WHERE project_request_code IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_eos_project_business_code
    ON eos_project (tenant_id, project_code, status, origin);

CREATE OR REPLACE FUNCTION eos_guard_project_business_identity()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.project_code IS DISTINCT FROM OLD.project_code
       OR NEW.project_request_code IS DISTINCT FROM OLD.project_request_code
       OR NEW.purpose_type IS DISTINCT FROM OLD.purpose_type
       OR NEW.origin IS DISTINCT FROM OLD.origin
       OR NEW.approval_evidence_ref IS DISTINCT FROM OLD.approval_evidence_ref
       OR NEW.approval_evidence_hash IS DISTINCT FROM OLD.approval_evidence_hash THEN
        RAISE EXCEPTION 'Project business identity and approval lineage are immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_eos_project_business_identity
BEFORE UPDATE ON eos_project
FOR EACH ROW EXECUTE FUNCTION eos_guard_project_business_identity();

CREATE OR REPLACE FUNCTION eos_guard_project_lifecycle()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.status <> OLD.status AND NOT (
        (OLD.status = 'ACTIVE' AND NEW.status IN ('INACTIVE', 'CLOSING'))
        OR
        (OLD.status = 'INACTIVE' AND NEW.status = 'ACTIVE')
        OR
        (OLD.status = 'CLOSING' AND NEW.status IN ('ACTIVE', 'CLOSED'))
    ) THEN
        RAISE EXCEPTION 'Project lifecycle transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status <> OLD.status AND NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'Project lifecycle version must advance by one'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_eos_project_lifecycle
BEFORE UPDATE ON eos_project
FOR EACH ROW EXECUTE FUNCTION eos_guard_project_lifecycle();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2531_eos_project_application_lifecycle',
    'Project application, annual business-code allocation, lifecycle, and resolver foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
