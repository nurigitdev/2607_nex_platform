BEGIN;

CREATE TABLE IF NOT EXISTS eos_legal_entity (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    company_code VARCHAR(64) NOT NULL,
    name VARCHAR(256) NOT NULL,
    functional_currency CHAR(3) NOT NULL,
    presentation_currency CHAR(3) NOT NULL,
    business_timezone VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    effective_from DATE NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_legal_entity PRIMARY KEY (tenant_id, company_id),
    CONSTRAINT ux_eos_legal_entity_code UNIQUE (tenant_id, company_code),
    CONSTRAINT ck_eos_legal_entity_currency CHECK (
        functional_currency ~ '^[A-Z]{3}$'
        AND presentation_currency ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT ck_eos_legal_entity_status CHECK (
        status IN ('ACTIVE', 'INACTIVE')
    ),
    CONSTRAINT ck_eos_legal_entity_version CHECK (version > 0)
);

CREATE INDEX IF NOT EXISTS ix_eos_legal_entity_effective
    ON eos_legal_entity (tenant_id, status, effective_from);

CREATE TABLE IF NOT EXISTS eos_project_company_binding (
    tenant_id VARCHAR(128) NOT NULL,
    binding_id UUID NOT NULL,
    project_id UUID NOT NULL,
    company_id UUID NOT NULL,
    valid_from DATE NOT NULL,
    valid_until DATE NULL,
    approved_proof_hash VARCHAR(71) NOT NULL,
    state VARCHAR(16) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_project_company_binding
        PRIMARY KEY (tenant_id, binding_id),
    CONSTRAINT fk_eos_project_company_project
        FOREIGN KEY (tenant_id, project_id)
        REFERENCES eos_project (tenant_id, project_id),
    CONSTRAINT fk_eos_project_company_entity
        FOREIGN KEY (tenant_id, company_id)
        REFERENCES eos_legal_entity (tenant_id, company_id),
    CONSTRAINT ck_eos_project_company_period CHECK (
        valid_until IS NULL OR valid_until > valid_from
    ),
    CONSTRAINT ck_eos_project_company_hash CHECK (
        approved_proof_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_project_company_state CHECK (
        state IN ('APPROVED', 'REVOKED')
    ),
    CONSTRAINT ck_eos_project_company_version CHECK (version > 0)
);

CREATE INDEX IF NOT EXISTS ix_eos_project_company_effective
    ON eos_project_company_binding (
        tenant_id, project_id, state, valid_from, valid_until
    );

CREATE INDEX IF NOT EXISTS ix_eos_project_company_entity
    ON eos_project_company_binding (tenant_id, company_id);

CREATE OR REPLACE FUNCTION eos_reject_project_company_overlap()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.state = 'APPROVED' AND EXISTS (
        SELECT 1
        FROM eos_project_company_binding existing
        WHERE existing.tenant_id = NEW.tenant_id
          AND existing.project_id = NEW.project_id
          AND existing.binding_id <> NEW.binding_id
          AND existing.state = 'APPROVED'
          AND (
              existing.valid_until IS NULL
              OR existing.valid_until > NEW.valid_from
          )
          AND (
              NEW.valid_until IS NULL
              OR existing.valid_from < NEW.valid_until
          )
    ) THEN
        RAISE EXCEPTION 'overlapping ProjectCompanyBinding'
            USING ERRCODE = '23505';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_eos_project_company_overlap
    ON eos_project_company_binding;

CREATE TRIGGER trg_eos_project_company_overlap
BEFORE INSERT OR UPDATE OF project_id, valid_from, valid_until, state
ON eos_project_company_binding
FOR EACH ROW
EXECUTE FUNCTION eos_reject_project_company_overlap();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2516_eos_legal_entity_project_binding',
    'NeX-EOS tenant-scoped LegalEntity and effective Project company binding'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
