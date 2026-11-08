BEGIN;

CREATE TABLE IF NOT EXISTS eos_org_unit (
    tenant_id VARCHAR(128) NOT NULL,
    org_unit_id UUID NOT NULL,
    org_unit_code VARCHAR(64) NOT NULL,
    name VARCHAR(256) NOT NULL,
    org_unit_type VARCHAR(16) NOT NULL,
    parent_org_unit_id UUID,
    status VARCHAR(16) NOT NULL,
    effective_from TIMESTAMPTZ NOT NULL,
    effective_until TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_org_unit PRIMARY KEY (tenant_id, org_unit_id),
    CONSTRAINT ux_eos_org_unit_code UNIQUE (tenant_id, org_unit_code),
    CONSTRAINT fk_eos_org_unit_parent
        FOREIGN KEY (tenant_id, parent_org_unit_id)
        REFERENCES eos_org_unit (tenant_id, org_unit_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_org_unit_type
        CHECK (org_unit_type IN ('PART', 'TEAM', 'GROUP', 'COMPANY')),
    CONSTRAINT ck_eos_org_unit_status
        CHECK (status IN ('ACTIVE', 'INACTIVE')),
    CONSTRAINT ck_eos_org_unit_period
        CHECK (effective_until IS NULL OR effective_until > effective_from),
    CONSTRAINT ck_eos_org_unit_version CHECK (version > 0)
);

CREATE TABLE IF NOT EXISTS eos_position (
    tenant_id VARCHAR(128) NOT NULL,
    position_id UUID NOT NULL,
    position_type VARCHAR(32) NOT NULL,
    org_unit_id UUID NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_position PRIMARY KEY (tenant_id, position_id),
    CONSTRAINT ux_eos_position_type UNIQUE (
        tenant_id,
        org_unit_id,
        position_type
    ),
    CONSTRAINT fk_eos_position_org_unit
        FOREIGN KEY (tenant_id, org_unit_id)
        REFERENCES eos_org_unit (tenant_id, org_unit_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_position_type CHECK (position_type IN (
        'PART_LEAD',
        'TEAM_LEAD',
        'GROUP_LEAD',
        'CEO',
        'CHAIRMAN'
    )),
    CONSTRAINT ck_eos_position_status
        CHECK (status IN ('ACTIVE', 'INACTIVE'))
);

CREATE TABLE IF NOT EXISTS eos_position_assignment (
    tenant_id VARCHAR(128) NOT NULL,
    position_assignment_id UUID NOT NULL,
    position_id UUID NOT NULL,
    principal_ref_type VARCHAR(32) NOT NULL,
    principal_id VARCHAR(128) NOT NULL,
    effective_from TIMESTAMPTZ NOT NULL,
    effective_until TIMESTAMPTZ,
    status VARCHAR(16) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_position_assignment
        PRIMARY KEY (tenant_id, position_assignment_id),
    CONSTRAINT fk_eos_pos_assignment_position
        FOREIGN KEY (tenant_id, position_id)
        REFERENCES eos_position (tenant_id, position_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_pos_assignment_ref_type
        CHECK (principal_ref_type = 'oa.user'),
    CONSTRAINT ck_eos_pos_assignment_principal
        CHECK (principal_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'),
    CONSTRAINT ck_eos_pos_assignment_period
        CHECK (effective_until IS NULL OR effective_until > effective_from),
    CONSTRAINT ck_eos_pos_assignment_status
        CHECK (status IN ('ACTIVE', 'INACTIVE')),
    CONSTRAINT ck_eos_pos_assignment_version CHECK (version > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_eos_pos_assignment_active
    ON eos_position_assignment (tenant_id, position_id)
    WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS ix_eos_pos_assignment_principal
    ON eos_position_assignment (
        tenant_id,
        principal_ref_type,
        principal_id,
        status
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2502_eos_organization_core',
    'NeX-EOS organization units, positions, and effective assignments'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
