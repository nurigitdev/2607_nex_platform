BEGIN;

CREATE TABLE IF NOT EXISTS eos_material_commitment (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    commitment_id UUID NOT NULL,
    acquisition_ref VARCHAR(256) NOT NULL,
    acquisition_revision INTEGER NOT NULL,
    component_ref VARCHAR(256) NOT NULL,
    journal_id UUID NOT NULL,
    journal_line_no INTEGER NOT NULL,
    period_id UUID NOT NULL,
    account_id UUID NOT NULL,
    source_project_id UUID NOT NULL,
    source_project_code VARCHAR(11) NOT NULL,
    material_ref VARCHAR(256) NOT NULL,
    lot_ref VARCHAR(256),
    quantity_unit VARCHAR(16) NOT NULL,
    acquired_quantity NUMERIC(20, 4) NOT NULL,
    acquisition_amount_functional NUMERIC(20, 4) NOT NULL,
    assigned_quantity NUMERIC(20, 4) NOT NULL,
    assigned_amount_functional NUMERIC(20, 4) NOT NULL,
    unassigned_quantity NUMERIC(20, 4) NOT NULL,
    unassigned_amount_functional NUMERIC(20, 4) NOT NULL,
    functional_currency VARCHAR(3) NOT NULL,
    evidence_ref VARCHAR(256) NOT NULL,
    evidence_hash VARCHAR(71) NOT NULL,
    approval_ref VARCHAR(256) NOT NULL,
    approval_hash VARCHAR(71) NOT NULL,
    policy_hash VARCHAR(71) NOT NULL,
    reconciliation_state VARCHAR(16) NOT NULL,
    commitment_hash VARCHAR(71) NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, company_id, commitment_id),
    CONSTRAINT ux_eos_material_commit_source UNIQUE (
        tenant_id, company_id, acquisition_ref, acquisition_revision,
        component_ref
    ),
    CONSTRAINT ux_eos_material_commit_hash UNIQUE (
        tenant_id, company_id, commitment_hash
    ),
    CONSTRAINT fk_eos_material_commit_journal FOREIGN KEY (
        tenant_id, company_id, journal_id, journal_line_no
    ) REFERENCES eos_journal_line (
        tenant_id, company_id, journal_id, line_no
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_material_commit_revision CHECK (
        acquisition_revision > 0
    ),
    CONSTRAINT ck_eos_material_commit_line CHECK (journal_line_no > 0),
    CONSTRAINT ck_eos_material_commit_positive CHECK (
        acquired_quantity > 0 AND acquisition_amount_functional > 0
    ),
    CONSTRAINT ck_eos_material_commit_qty_balance CHECK (
        assigned_quantity >= 0 AND unassigned_quantity >= 0
        AND acquired_quantity = assigned_quantity + unassigned_quantity
    ),
    CONSTRAINT ck_eos_material_commit_amt_balance CHECK (
        assigned_amount_functional >= 0
        AND unassigned_amount_functional >= 0
        AND acquisition_amount_functional =
            assigned_amount_functional + unassigned_amount_functional
    ),
    CONSTRAINT ck_eos_material_commit_reconcile CHECK (
        reconciliation_state IN ('VERIFIED', 'PENDING', 'BLOCKED')
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_material_commit_journal
    ON eos_material_commitment (
        tenant_id, company_id, journal_id, journal_line_no
    );
CREATE INDEX IF NOT EXISTS ix_eos_material_commit_queue
    ON eos_material_commitment (
        tenant_id, company_id, reconciliation_state, acquired_at
    );

CREATE TABLE IF NOT EXISTS eos_material_attribution (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    commitment_id UUID NOT NULL,
    line_no INTEGER NOT NULL,
    attribution_kind VARCHAR(16) NOT NULL,
    project_id UUID,
    project_code VARCHAR(11),
    work_code VARCHAR(16),
    attributed_quantity NUMERIC(20, 4) NOT NULL,
    attributed_amount_functional NUMERIC(20, 4) NOT NULL,
    basis_kind VARCHAR(32) NOT NULL,
    basis_ref VARCHAR(256) NOT NULL,
    basis_hash VARCHAR(71) NOT NULL,
    line_hash VARCHAR(71) NOT NULL,
    PRIMARY KEY (tenant_id, company_id, commitment_id, line_no),
    CONSTRAINT ux_eos_material_attr_hash UNIQUE (
        tenant_id, company_id, commitment_id, line_hash
    ),
    CONSTRAINT fk_eos_material_attr_commit FOREIGN KEY (
        tenant_id, company_id, commitment_id
    ) REFERENCES eos_material_commitment (
        tenant_id, company_id, commitment_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_material_attr_project FOREIGN KEY (
        tenant_id, project_id
    ) REFERENCES eos_project (
        tenant_id, project_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_material_attr_line CHECK (line_no > 0),
    CONSTRAINT ck_eos_material_attr_positive CHECK (
        attributed_quantity > 0 AND attributed_amount_functional > 0
    ),
    CONSTRAINT ck_eos_material_attr_kind CHECK (
        attribution_kind IN ('PROJECT', 'UNASSIGNED')
    ),
    CONSTRAINT ck_eos_material_attr_basis CHECK (
        basis_kind IN (
            'DIRECT_PROJECT', 'APPROVED_QUANTITY', 'APPROVED_RATIO',
            'BOM_PLAN', 'UNASSIGNED'
        )
    ),
    CONSTRAINT ck_eos_material_attr_target CHECK (
        (
            attribution_kind = 'PROJECT'
            AND project_id IS NOT NULL
            AND project_code IS NOT NULL
            AND basis_kind <> 'UNASSIGNED'
        ) OR (
            attribution_kind = 'UNASSIGNED'
            AND project_id IS NULL
            AND project_code IS NULL
            AND work_code IS NULL
            AND basis_kind = 'UNASSIGNED'
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_material_attr_project
    ON eos_material_attribution (
        tenant_id, company_id, project_id, commitment_id
    );
CREATE INDEX IF NOT EXISTS ix_eos_material_attr_unassigned
    ON eos_material_attribution (
        tenant_id, company_id, attribution_kind, commitment_id
    );

CREATE OR REPLACE FUNCTION eos_reject_material_commit_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'material commitment records are append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_eos_material_commit_immutable
    ON eos_material_commitment;
CREATE TRIGGER trg_eos_material_commit_immutable
    BEFORE UPDATE OR DELETE ON eos_material_commitment
    FOR EACH ROW EXECUTE FUNCTION eos_reject_material_commit_mutation();

DROP TRIGGER IF EXISTS trg_eos_material_attr_immutable
    ON eos_material_attribution;
CREATE TRIGGER trg_eos_material_attr_immutable
    BEFORE UPDATE OR DELETE ON eos_material_attribution
    FOR EACH ROW EXECUTE FUNCTION eos_reject_material_commit_mutation();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2546_eos_material_commitment',
    'Material commitment and Project inventory attribution foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
