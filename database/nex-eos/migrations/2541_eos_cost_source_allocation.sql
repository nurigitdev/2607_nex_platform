BEGIN;

CREATE TABLE IF NOT EXISTS eos_cost_source_pool (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    pool_id UUID NOT NULL,
    journal_id UUID NOT NULL,
    journal_line_no INTEGER NOT NULL,
    eligible_component_id VARCHAR(128) NOT NULL,
    source_business_operation_id UUID NOT NULL,
    source_project_id UUID NOT NULL,
    source_project_code VARCHAR(11) NOT NULL,
    source_kind VARCHAR(32) NOT NULL,
    allocation_mode VARCHAR(32) NOT NULL,
    source_amount_functional NUMERIC(20, 4) NOT NULL,
    eligible_amount_functional NUMERIC(20, 4) NOT NULL,
    functional_currency VARCHAR(3) NOT NULL,
    account_id UUID NOT NULL,
    account_category VARCHAR(16) NOT NULL,
    monetary_class VARCHAR(16) NOT NULL,
    recognition_date DATE NOT NULL,
    recognized_at TIMESTAMPTZ NOT NULL,
    period_id UUID NOT NULL,
    source_record_ref VARCHAR(256) NOT NULL,
    source_hash VARCHAR(71) NOT NULL,
    eligibility_policy_hash VARCHAR(71) NOT NULL,
    pool_state VARCHAR(16) NOT NULL,
    source_journal_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, company_id, pool_id),
    CONSTRAINT ux_eos_cost_pool_source UNIQUE (
        tenant_id,
        company_id,
        journal_id,
        journal_line_no,
        eligible_component_id
    ),
    CONSTRAINT fk_eos_cost_pool_journal FOREIGN KEY (
        tenant_id, company_id, journal_id
    ) REFERENCES eos_journal_header (
        tenant_id, company_id, journal_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_cost_pool_line FOREIGN KEY (
        tenant_id, company_id, journal_id, journal_line_no
    ) REFERENCES eos_journal_line (
        tenant_id, company_id, journal_id, line_no
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_cost_pool_operation FOREIGN KEY (
        tenant_id, source_business_operation_id
    ) REFERENCES eos_business_operation (
        tenant_id, business_operation_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_cost_pool_project FOREIGN KEY (
        tenant_id, source_project_id
    ) REFERENCES eos_project (
        tenant_id, project_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_cost_pool_account FOREIGN KEY (
        tenant_id, account_id
    ) REFERENCES eos_account (
        tenant_id, account_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_cost_pool_period FOREIGN KEY (
        tenant_id, company_id, period_id
    ) REFERENCES eos_accounting_period (
        tenant_id, company_id, period_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_cost_pool_line_no CHECK (journal_line_no > 0),
    CONSTRAINT ck_eos_cost_pool_source_kind CHECK (
        source_kind IN (
            'PAYROLL', 'PURCHASE', 'SERVICE', 'SHARED_EXPENSE',
            'REVENUE', 'FX_GAIN_LOSS', 'OTHER'
        )
    ),
    CONSTRAINT ck_eos_cost_pool_mode CHECK (
        allocation_mode IN ('DIRECT', 'MANAGEMENT_ALLOCATION', 'GL_COST_TRANSFER')
    ),
    CONSTRAINT ck_eos_cost_pool_category CHECK (
        account_category IN ('REVENUE', 'EXPENSE')
    ),
    CONSTRAINT ck_eos_cost_pool_monetary CHECK (
        monetary_class IN ('MONETARY', 'NON_MONETARY')
    ),
    CONSTRAINT ck_eos_cost_pool_state CHECK (
        pool_state IN ('OPEN', 'ALLOCATED', 'REVERSED', 'ON_HOLD')
    ),
    CONSTRAINT ck_eos_cost_pool_amount CHECK (
        source_amount_functional <> 0
        AND eligible_amount_functional = source_amount_functional
    ),
    CONSTRAINT ck_eos_cost_pool_currency CHECK (
        functional_currency ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT ck_eos_cost_pool_project_code CHECK (
        source_project_code ~ '^[A-Z0-9]{4}[DMSOIG][0-9]{6}$'
    ),
    CONSTRAINT ck_eos_cost_pool_hashes CHECK (
        source_hash ~ '^sha256:[0-9a-f]{64}$'
        AND eligibility_policy_hash ~ '^sha256:[0-9a-f]{64}$'
        AND source_journal_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_cost_pool_state
    ON eos_cost_source_pool (
        tenant_id, company_id, pool_state, recognition_date, pool_id
    );

CREATE INDEX IF NOT EXISTS ix_eos_cost_pool_project
    ON eos_cost_source_pool (
        tenant_id, company_id, source_project_id, recognition_date
    );

CREATE TABLE IF NOT EXISTS eos_cost_allocation_plan (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    plan_id UUID NOT NULL,
    plan_revision INTEGER NOT NULL,
    source_kind VARCHAR(32) NOT NULL,
    scope_type VARCHAR(32) NOT NULL,
    basis_kind VARCHAR(32) NOT NULL,
    rule_release_hash VARCHAR(71) NOT NULL,
    basis_source_ref VARCHAR(256) NOT NULL,
    basis_source_hash VARCHAR(71) NOT NULL,
    effective_start DATE NOT NULL,
    effective_end DATE,
    approved_by VARCHAR(128) NOT NULL,
    approved_proof VARCHAR(256) NOT NULL,
    state VARCHAR(16) NOT NULL,
    plan_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, company_id, plan_id, plan_revision),
    CONSTRAINT fk_eos_cost_plan_company FOREIGN KEY (
        tenant_id, company_id
    ) REFERENCES eos_legal_entity (
        tenant_id, company_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ux_eos_cost_plan_hash UNIQUE (
        tenant_id, company_id, plan_hash
    ),
    CONSTRAINT ck_eos_cost_plan_revision CHECK (plan_revision > 0),
    CONSTRAINT ck_eos_cost_plan_basis CHECK (
        basis_kind IN (
            'ACTUAL_WORK', 'APPROVED_PLAN', 'USAGE',
            'HEADCOUNT_CASCADE', 'JUSTIFIED_PERCENTAGE'
        )
    ),
    CONSTRAINT ck_eos_cost_plan_state CHECK (
        state IN ('DRAFT', 'APPROVED', 'REVOKED', 'SUPERSEDED')
    ),
    CONSTRAINT ck_eos_cost_plan_period CHECK (
        effective_end IS NULL OR effective_end >= effective_start
    )
);

CREATE TABLE IF NOT EXISTS eos_cost_allocation_plan_line (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    plan_id UUID NOT NULL,
    plan_revision INTEGER NOT NULL,
    line_no INTEGER NOT NULL,
    project_id UUID NOT NULL,
    project_code VARCHAR(11) NOT NULL,
    work_code VARCHAR(32),
    basis_units NUMERIC(24, 8) NOT NULL,
    allocation_ratio NUMERIC(18, 12) NOT NULL,
    eligibility_hash VARCHAR(71) NOT NULL,
    confidentiality_class VARCHAR(32) NOT NULL,
    line_hash VARCHAR(71) NOT NULL,
    PRIMARY KEY (
        tenant_id, company_id, plan_id, plan_revision, line_no
    ),
    CONSTRAINT fk_eos_cost_plan_line_plan FOREIGN KEY (
        tenant_id, company_id, plan_id, plan_revision
    ) REFERENCES eos_cost_allocation_plan (
        tenant_id, company_id, plan_id, plan_revision
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_cost_plan_line_project FOREIGN KEY (
        tenant_id, project_id
    ) REFERENCES eos_project (
        tenant_id, project_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_cost_plan_line_no CHECK (line_no > 0),
    CONSTRAINT ck_eos_cost_plan_line_basis CHECK (basis_units >= 0),
    CONSTRAINT ck_eos_cost_plan_line_ratio CHECK (
        allocation_ratio >= 0 AND allocation_ratio <= 1
    )
);

CREATE TABLE IF NOT EXISTS eos_cost_allocation_batch (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    batch_id UUID NOT NULL,
    plan_id UUID NOT NULL,
    plan_revision INTEGER NOT NULL,
    period_id UUID NOT NULL,
    source_set_hash VARCHAR(71) NOT NULL,
    functional_currency VARCHAR(3) NOT NULL,
    state VARCHAR(32) NOT NULL,
    allocated_total NUMERIC(20, 4) NOT NULL,
    unallocated_total NUMERIC(20, 4) NOT NULL,
    reconciliation_hash VARCHAR(71),
    business_operation_id UUID NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    outbox_event_id UUID,
    committed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, company_id, batch_id),
    CONSTRAINT fk_eos_cost_batch_plan FOREIGN KEY (
        tenant_id, company_id, plan_id, plan_revision
    ) REFERENCES eos_cost_allocation_plan (
        tenant_id, company_id, plan_id, plan_revision
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_cost_batch_period FOREIGN KEY (
        tenant_id, company_id, period_id
    ) REFERENCES eos_accounting_period (
        tenant_id, company_id, period_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_cost_batch_operation FOREIGN KEY (
        tenant_id, business_operation_id
    ) REFERENCES eos_business_operation (
        tenant_id, business_operation_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ux_eos_cost_batch_operation UNIQUE (
        tenant_id, business_operation_id
    ),
    CONSTRAINT ux_eos_cost_batch_idempotency UNIQUE (
        tenant_id, company_id, idempotency_key
    ),
    CONSTRAINT ck_eos_cost_batch_state CHECK (
        state IN ('DRAFT', 'COMMITTED', 'RECONCILIATION_FAILED', 'REVERSED')
    )
);

CREATE TABLE IF NOT EXISTS eos_cost_allocation_line (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    batch_id UUID NOT NULL,
    line_no INTEGER NOT NULL,
    pool_id UUID NOT NULL,
    project_id UUID NOT NULL,
    project_code VARCHAR(11) NOT NULL,
    work_code VARCHAR(32),
    basis_source_ref VARCHAR(256) NOT NULL,
    basis_source_hash VARCHAR(71) NOT NULL,
    basis_units NUMERIC(24, 8) NOT NULL,
    allocation_ratio NUMERIC(18, 12) NOT NULL,
    allocated_amount_functional NUMERIC(20, 4) NOT NULL,
    rounding_delta NUMERIC(20, 4) NOT NULL,
    allocation_mode VARCHAR(32) NOT NULL,
    original_source_line_ref VARCHAR(256) NOT NULL,
    evidence_hash VARCHAR(71) NOT NULL,
    status VARCHAR(16) NOT NULL,
    PRIMARY KEY (tenant_id, company_id, batch_id, line_no),
    CONSTRAINT fk_eos_cost_line_batch FOREIGN KEY (
        tenant_id, company_id, batch_id
    ) REFERENCES eos_cost_allocation_batch (
        tenant_id, company_id, batch_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_cost_line_pool FOREIGN KEY (
        tenant_id, company_id, pool_id
    ) REFERENCES eos_cost_source_pool (
        tenant_id, company_id, pool_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_cost_line_project FOREIGN KEY (
        tenant_id, project_id
    ) REFERENCES eos_project (
        tenant_id, project_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_cost_line_no CHECK (line_no > 0),
    CONSTRAINT ck_eos_cost_line_ratio CHECK (
        allocation_ratio >= 0 AND allocation_ratio <= 1
    ),
    CONSTRAINT ck_eos_cost_line_mode CHECK (
        allocation_mode IN ('MANAGEMENT_ALLOCATION', 'GL_COST_TRANSFER')
    ),
    CONSTRAINT ck_eos_cost_line_status CHECK (
        status IN ('ALLOCATED', 'REVERSED')
    )
);

CREATE TABLE IF NOT EXISTS eos_cost_allocation_adjustment (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    adjustment_id UUID NOT NULL,
    original_batch_id UUID NOT NULL,
    original_batch_line_no INTEGER NOT NULL,
    original_journal_id UUID NOT NULL,
    new_journal_id UUID,
    delta_amount NUMERIC(20, 4) NOT NULL,
    reason VARCHAR(512) NOT NULL,
    effective_period_id UUID NOT NULL,
    approved_proof VARCHAR(256) NOT NULL,
    operation_id UUID NOT NULL,
    adjustment_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, company_id, adjustment_id),
    CONSTRAINT fk_eos_cost_adjustment_line FOREIGN KEY (
        tenant_id, company_id, original_batch_id, original_batch_line_no
    ) REFERENCES eos_cost_allocation_line (
        tenant_id, company_id, batch_id, line_no
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_cost_adjustment_journal FOREIGN KEY (
        tenant_id, company_id, original_journal_id
    ) REFERENCES eos_journal_header (
        tenant_id, company_id, journal_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_cost_adjustment_new_journal FOREIGN KEY (
        tenant_id, company_id, new_journal_id
    ) REFERENCES eos_journal_header (
        tenant_id, company_id, journal_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_cost_adjustment_period FOREIGN KEY (
        tenant_id, company_id, effective_period_id
    ) REFERENCES eos_accounting_period (
        tenant_id, company_id, period_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_cost_adjustment_operation FOREIGN KEY (
        tenant_id, operation_id
    ) REFERENCES eos_business_operation (
        tenant_id, business_operation_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ux_eos_cost_adjustment_hash UNIQUE (
        tenant_id, company_id, adjustment_hash
    ),
    CONSTRAINT ck_eos_cost_adjustment_delta CHECK (delta_amount <> 0)
);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2541_eos_cost_source_allocation',
    'Cost source eligibility and immutable allocation lineage foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
