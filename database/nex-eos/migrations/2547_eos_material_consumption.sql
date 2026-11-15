BEGIN;

CREATE TABLE IF NOT EXISTS eos_material_consumption (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    consumption_id UUID NOT NULL,
    consumption_ref VARCHAR(256) NOT NULL,
    consumption_revision INTEGER NOT NULL,
    component_ref VARCHAR(256) NOT NULL,
    cost_pool_id UUID NOT NULL,
    period_id UUID NOT NULL,
    project_id UUID NOT NULL,
    project_code VARCHAR(11) NOT NULL,
    work_code VARCHAR(16),
    material_ref VARCHAR(256) NOT NULL,
    quantity_unit VARCHAR(16) NOT NULL,
    consumed_quantity NUMERIC(20, 4) NOT NULL,
    recognized_cost_functional NUMERIC(20, 4) NOT NULL,
    released_carrying_amount_functional NUMERIC(20, 4) NOT NULL,
    valuation_variance_functional NUMERIC(20, 4) NOT NULL,
    functional_currency VARCHAR(3) NOT NULL,
    evidence_ref VARCHAR(256) NOT NULL,
    evidence_hash VARCHAR(71) NOT NULL,
    approval_ref VARCHAR(256) NOT NULL,
    approval_hash VARCHAR(71) NOT NULL,
    policy_hash VARCHAR(71) NOT NULL,
    reconciliation_state VARCHAR(16) NOT NULL,
    consumption_hash VARCHAR(71) NOT NULL,
    consumed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, company_id, consumption_id),
    CONSTRAINT ux_eos_material_consume_source UNIQUE (
        tenant_id, company_id, consumption_ref, consumption_revision,
        component_ref
    ),
    CONSTRAINT ux_eos_material_consume_pool UNIQUE (
        tenant_id, company_id, cost_pool_id
    ),
    CONSTRAINT ux_eos_material_consume_hash UNIQUE (
        tenant_id, company_id, consumption_hash
    ),
    CONSTRAINT fk_eos_material_consume_pool FOREIGN KEY (
        tenant_id, company_id, cost_pool_id
    ) REFERENCES eos_cost_source_pool (
        tenant_id, company_id, pool_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_material_consume_project FOREIGN KEY (
        tenant_id, project_id
    ) REFERENCES eos_project (
        tenant_id, project_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_material_consume_revision CHECK (
        consumption_revision > 0
    ),
    CONSTRAINT ck_eos_material_consume_positive CHECK (
        consumed_quantity > 0
        AND recognized_cost_functional > 0
        AND released_carrying_amount_functional > 0
    ),
    CONSTRAINT ck_eos_material_consume_variance CHECK (
        valuation_variance_functional =
            recognized_cost_functional - released_carrying_amount_functional
    ),
    CONSTRAINT ck_eos_material_consume_reconcile CHECK (
        reconciliation_state = 'VERIFIED'
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_material_consume_project
    ON eos_material_consumption (
        tenant_id, company_id, project_id, period_id, created_at
    );

CREATE TABLE IF NOT EXISTS eos_material_release (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    consumption_id UUID NOT NULL,
    line_no INTEGER NOT NULL,
    commitment_id UUID NOT NULL,
    attribution_line_no INTEGER NOT NULL,
    released_quantity NUMERIC(20, 4) NOT NULL,
    released_amount_functional NUMERIC(20, 4) NOT NULL,
    line_hash VARCHAR(71) NOT NULL,
    PRIMARY KEY (tenant_id, company_id, consumption_id, line_no),
    CONSTRAINT ux_eos_material_release_source UNIQUE (
        tenant_id, company_id, consumption_id,
        commitment_id, attribution_line_no
    ),
    CONSTRAINT ux_eos_material_release_hash UNIQUE (
        tenant_id, company_id, consumption_id, line_hash
    ),
    CONSTRAINT fk_eos_material_release_consume FOREIGN KEY (
        tenant_id, company_id, consumption_id
    ) REFERENCES eos_material_consumption (
        tenant_id, company_id, consumption_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_material_release_attr FOREIGN KEY (
        tenant_id, company_id, commitment_id, attribution_line_no
    ) REFERENCES eos_material_attribution (
        tenant_id, company_id, commitment_id, line_no
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_material_release_line CHECK (
        line_no > 0 AND attribution_line_no > 0
    ),
    CONSTRAINT ck_eos_material_release_positive CHECK (
        released_quantity > 0 AND released_amount_functional > 0
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_material_release_attr
    ON eos_material_release (
        tenant_id, company_id, commitment_id, attribution_line_no
    );

CREATE OR REPLACE FUNCTION eos_reject_material_consumption_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'material consumption records are append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_eos_material_consume_immutable
    ON eos_material_consumption;
CREATE TRIGGER trg_eos_material_consume_immutable
    BEFORE UPDATE OR DELETE ON eos_material_consumption
    FOR EACH ROW EXECUTE FUNCTION eos_reject_material_consumption_mutation();

DROP TRIGGER IF EXISTS trg_eos_material_release_immutable
    ON eos_material_release;
CREATE TRIGGER trg_eos_material_release_immutable
    BEFORE UPDATE OR DELETE ON eos_material_release
    FOR EACH ROW EXECUTE FUNCTION eos_reject_material_consumption_mutation();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2547_eos_material_consumption',
    'Material consumption release and POSTED cost reconciliation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
