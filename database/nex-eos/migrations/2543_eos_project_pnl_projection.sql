BEGIN;

CREATE TABLE IF NOT EXISTS eos_project_pnl_projection (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    projection_id UUID NOT NULL,
    project_id UUID NOT NULL,
    project_code VARCHAR(11) NOT NULL,
    period_id UUID NOT NULL,
    projection_version INTEGER NOT NULL,
    functional_currency VARCHAR(3) NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    posting_watermark VARCHAR(256) NOT NULL,
    posting_watermark_at TIMESTAMPTZ NOT NULL,
    allocation_watermark VARCHAR(256) NOT NULL,
    allocation_watermark_at TIMESTAMPTZ NOT NULL,
    budget_watermark VARCHAR(256),
    budget_watermark_at TIMESTAMPTZ,
    payroll_evidence_watermark VARCHAR(256),
    payroll_evidence_watermark_at TIMESTAMPTZ,
    labor_effort_watermark VARCHAR(256),
    labor_effort_watermark_at TIMESTAMPTZ,
    material_commitment_watermark VARCHAR(256),
    material_commitment_watermark_at TIMESTAMPTZ,
    reconciliation_status VARCHAR(16) NOT NULL,
    freshness_status VARCHAR(16) NOT NULL,
    staleness_seconds BIGINT NOT NULL,
    posted_revenue NUMERIC(20, 4) NOT NULL,
    posted_direct_cost NUMERIC(20, 4) NOT NULL,
    posted_allocated_cost NUMERIC(20, 4) NOT NULL,
    posted_operating_result NUMERIC(20, 4) NOT NULL,
    operating_unallocated_cost NUMERIC(20, 4) NOT NULL,
    planned_budget NUMERIC(20, 4) NOT NULL,
    budget_actual NUMERIC(20, 4) NOT NULL,
    budget_variance NUMERIC(20, 4) NOT NULL,
    approved_not_posted NUMERIC(20, 4) NOT NULL,
    forecast NUMERIC(20, 4) NOT NULL,
    data_classification VARCHAR(32) NOT NULL,
    projection_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, company_id, projection_id),
    CONSTRAINT ux_eos_project_pnl_version UNIQUE (
        tenant_id, company_id, project_id, period_id, projection_version
    ),
    CONSTRAINT ux_eos_project_pnl_hash UNIQUE (
        tenant_id, company_id, projection_hash
    ),
    CONSTRAINT fk_eos_project_pnl_company FOREIGN KEY (
        tenant_id, company_id
    ) REFERENCES eos_legal_entity (
        tenant_id, company_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_project_pnl_project FOREIGN KEY (
        tenant_id, project_id
    ) REFERENCES eos_project (
        tenant_id, project_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_project_pnl_period FOREIGN KEY (
        tenant_id, company_id, period_id
    ) REFERENCES eos_accounting_period (
        tenant_id, company_id, period_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_project_pnl_version CHECK (projection_version > 0),
    CONSTRAINT ck_eos_project_pnl_code CHECK (
        project_code ~ '^[A-Z0-9]{4}[DMSOIG][0-9]{6}$'
    ),
    CONSTRAINT ck_eos_project_pnl_currency CHECK (
        functional_currency ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT ck_eos_project_pnl_reconciliation CHECK (
        reconciliation_status IN ('VERIFIED', 'PENDING', 'BLOCKED', 'PARTIAL')
    ),
    CONSTRAINT ck_eos_project_pnl_freshness CHECK (
        freshness_status IN ('CURRENT', 'STALE', 'UNKNOWN')
    ),
    CONSTRAINT ck_eos_project_pnl_classification CHECK (
        data_classification IN (
            'INTERNAL_FINANCIAL', 'CONFIDENTIAL_FINANCIAL', 'PAYROLL_SENSITIVE'
        )
    ),
    CONSTRAINT ck_eos_project_pnl_staleness CHECK (staleness_seconds >= 0),
    CONSTRAINT ck_eos_project_pnl_amounts CHECK (
        posted_revenue >= 0
        AND posted_direct_cost >= 0
        AND posted_allocated_cost >= 0
        AND operating_unallocated_cost >= 0
        AND planned_budget >= 0
        AND budget_actual >= 0
        AND approved_not_posted >= 0
        AND forecast >= 0
    ),
    CONSTRAINT ck_eos_project_pnl_result CHECK (
        posted_operating_result =
            posted_revenue - posted_direct_cost - posted_allocated_cost
    ),
    CONSTRAINT ck_eos_project_pnl_hash CHECK (
        projection_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_project_pnl_required_watermarks CHECK (
        char_length(posting_watermark) > 0
        AND char_length(allocation_watermark) > 0
        AND posting_watermark_at <= as_of
        AND allocation_watermark_at <= as_of
    ),
    CONSTRAINT ck_eos_project_pnl_optional_watermarks CHECK (
        (budget_watermark IS NULL) = (budget_watermark_at IS NULL)
        AND (payroll_evidence_watermark IS NULL) =
            (payroll_evidence_watermark_at IS NULL)
        AND (labor_effort_watermark IS NULL) =
            (labor_effort_watermark_at IS NULL)
        AND (material_commitment_watermark IS NULL) =
            (material_commitment_watermark_at IS NULL)
        AND (budget_watermark_at IS NULL OR budget_watermark_at <= as_of)
        AND (
            payroll_evidence_watermark_at IS NULL
            OR payroll_evidence_watermark_at <= as_of
        )
        AND (
            labor_effort_watermark_at IS NULL
            OR labor_effort_watermark_at <= as_of
        )
        AND (
            material_commitment_watermark_at IS NULL
            OR material_commitment_watermark_at <= as_of
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_project_pnl_lookup
    ON eos_project_pnl_projection (
        tenant_id, company_id, project_id, period_id, projection_version DESC
    );

CREATE INDEX IF NOT EXISTS ix_eos_project_pnl_freshness
    ON eos_project_pnl_projection (
        tenant_id, company_id, freshness_status, as_of
    );

CREATE TABLE IF NOT EXISTS eos_project_pnl_component (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    projection_id UUID NOT NULL,
    line_no INTEGER NOT NULL,
    classification VARCHAR(40) NOT NULL,
    rollup_class VARCHAR(24) NOT NULL,
    source_kind VARCHAR(24) NOT NULL,
    account_id UUID,
    work_code VARCHAR(32),
    functional_amount NUMERIC(20, 4) NOT NULL,
    confirmed BOOLEAN NOT NULL,
    source_ref VARCHAR(256) NOT NULL,
    source_hash VARCHAR(71) NOT NULL,
    data_classification VARCHAR(32) NOT NULL,
    component_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, company_id, projection_id, line_no),
    CONSTRAINT ux_eos_project_pnl_component_hash UNIQUE (
        tenant_id, company_id, projection_id, component_hash
    ),
    CONSTRAINT fk_eos_project_pnl_component_projection FOREIGN KEY (
        tenant_id, company_id, projection_id
    ) REFERENCES eos_project_pnl_projection (
        tenant_id, company_id, projection_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_project_pnl_component_account FOREIGN KEY (
        tenant_id, account_id
    ) REFERENCES eos_account (
        tenant_id, account_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_project_pnl_component_line CHECK (line_no > 0),
    CONSTRAINT ck_eos_project_pnl_component_amount CHECK (
        functional_amount <> 0
        AND (
            functional_amount > 0
            OR classification IN (
                'LABOR_ADJUSTMENT', 'MATERIAL_VARIANCE',
                'FX_REALIZED_GAIN_LOSS', 'FX_UNREALIZED_GAIN_LOSS'
            )
        )
    ),
    CONSTRAINT ck_eos_project_pnl_component_class CHECK (
        classification IN (
            'POSTED_REVENUE', 'POSTED_DIRECT_COST',
            'POSTED_ALLOCATED_COST', 'POSTED_LABOR_ALLOCATED',
            'UNALLOCATED', 'POSTED_PAYROLL_UNALLOCATED',
            'UNALLOCATED_LABOR_OVERHEAD', 'APPROVED_NOT_POSTED',
            'LABOR_ALLOCATION_PROVISIONAL', 'PLANNED_BUDGET', 'FORECAST',
            'PLANNED_LABOR', 'BOM_FORECAST', 'MATERIAL_COMMITTED',
            'UNASSIGNED_INVENTORY', 'LABOR_ADJUSTMENT',
            'MATERIAL_VARIANCE', 'FX_REALIZED_GAIN_LOSS',
            'FX_UNREALIZED_GAIN_LOSS'
        )
    ),
    CONSTRAINT ck_eos_project_pnl_component_rollup CHECK (
        rollup_class IN (
            'REVENUE', 'DIRECT_COST', 'ALLOCATED_COST', 'UNALLOCATED_COST',
            'NONFINAL', 'PROVISIONAL', 'BUDGET', 'FORECAST', 'COMMITMENT',
            'ADJUSTMENT'
        )
    ),
    CONSTRAINT ck_eos_project_pnl_component_source CHECK (
        source_kind IN (
            'REVENUE', 'PAYROLL', 'MATERIAL', 'SERVICE', 'SHARED_EXPENSE',
            'FX_GAIN_LOSS', 'OTHER'
        )
    ),
    CONSTRAINT ck_eos_project_pnl_component_data_class CHECK (
        data_classification IN (
            'INTERNAL_FINANCIAL', 'CONFIDENTIAL_FINANCIAL', 'PAYROLL_SENSITIVE'
        )
    ),
    CONSTRAINT ck_eos_project_pnl_component_hash CHECK (
        source_hash ~ '^sha256:[0-9a-f]{64}$'
        AND component_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_project_pnl_component_semantics CHECK (
        (classification = 'POSTED_REVENUE' AND rollup_class = 'REVENUE' AND confirmed)
        OR (
            classification = 'POSTED_DIRECT_COST'
            AND rollup_class = 'DIRECT_COST' AND confirmed
        )
        OR (
            classification IN ('POSTED_ALLOCATED_COST', 'POSTED_LABOR_ALLOCATED')
            AND rollup_class = 'ALLOCATED_COST' AND confirmed
        )
        OR (
            classification IN (
                'UNALLOCATED', 'POSTED_PAYROLL_UNALLOCATED',
                'UNALLOCATED_LABOR_OVERHEAD'
            )
            AND rollup_class = 'UNALLOCATED_COST' AND NOT confirmed
        )
        OR (
            classification = 'APPROVED_NOT_POSTED'
            AND rollup_class = 'NONFINAL' AND NOT confirmed
        )
        OR (
            classification = 'LABOR_ALLOCATION_PROVISIONAL'
            AND rollup_class = 'PROVISIONAL' AND NOT confirmed
        )
        OR (
            classification = 'PLANNED_BUDGET'
            AND rollup_class = 'BUDGET' AND NOT confirmed
        )
        OR (
            classification IN ('FORECAST', 'PLANNED_LABOR', 'BOM_FORECAST')
            AND rollup_class = 'FORECAST' AND NOT confirmed
        )
        OR (
            classification IN ('MATERIAL_COMMITTED', 'UNASSIGNED_INVENTORY')
            AND rollup_class = 'COMMITMENT' AND NOT confirmed
        )
        OR (
            classification IN (
                'LABOR_ADJUSTMENT', 'MATERIAL_VARIANCE',
                'FX_REALIZED_GAIN_LOSS', 'FX_UNREALIZED_GAIN_LOSS'
            )
            AND rollup_class = 'ADJUSTMENT' AND confirmed
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_project_pnl_component_class
    ON eos_project_pnl_component (
        tenant_id, company_id, projection_id, classification
    );

CREATE INDEX IF NOT EXISTS ix_eos_project_pnl_component_source
    ON eos_project_pnl_component (
        tenant_id, company_id, source_hash
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2543_eos_project_pnl_projection',
    'Project P&L immutable projection version and typed component foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
