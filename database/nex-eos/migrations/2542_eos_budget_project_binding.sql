BEGIN;

CREATE TABLE IF NOT EXISTS eos_budget (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    budget_id UUID NOT NULL,
    budget_version INTEGER NOT NULL,
    fiscal_year INTEGER NOT NULL,
    account_id UUID,
    budget_category VARCHAR(64) NOT NULL,
    approved_currency VARCHAR(3) NOT NULL,
    approved_functional_amount NUMERIC(20, 4) NOT NULL,
    approved_by VARCHAR(128) NOT NULL,
    approved_proof VARCHAR(256) NOT NULL,
    source_ref VARCHAR(256) NOT NULL,
    source_hash VARCHAR(71) NOT NULL,
    budget_hash VARCHAR(71) NOT NULL,
    state VARCHAR(16) NOT NULL,
    business_operation_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, company_id, budget_id, budget_version),
    CONSTRAINT ux_eos_budget_hash UNIQUE (
        tenant_id, company_id, budget_hash
    ),
    CONSTRAINT ux_eos_budget_operation UNIQUE (
        tenant_id, business_operation_id
    ),
    CONSTRAINT fk_eos_budget_company FOREIGN KEY (
        tenant_id, company_id
    ) REFERENCES eos_legal_entity (
        tenant_id, company_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_budget_account FOREIGN KEY (
        tenant_id, account_id
    ) REFERENCES eos_account (
        tenant_id, account_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_budget_operation FOREIGN KEY (
        tenant_id, business_operation_id
    ) REFERENCES eos_business_operation (
        tenant_id, business_operation_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_budget_version CHECK (budget_version > 0),
    CONSTRAINT ck_eos_budget_year CHECK (fiscal_year BETWEEN 2000 AND 9999),
    CONSTRAINT ck_eos_budget_amount CHECK (approved_functional_amount > 0),
    CONSTRAINT ck_eos_budget_currency CHECK (
        approved_currency ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT ck_eos_budget_hashes CHECK (
        source_hash ~ '^sha256:[0-9a-f]{64}$'
        AND budget_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_budget_state CHECK (state = 'APPROVED')
);

CREATE INDEX IF NOT EXISTS ix_eos_budget_current
    ON eos_budget (
        tenant_id, company_id, fiscal_year, state, budget_id, budget_version
    );

CREATE TABLE IF NOT EXISTS eos_project_budget_binding (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    project_id UUID NOT NULL,
    binding_id UUID NOT NULL,
    binding_version INTEGER NOT NULL,
    project_code VARCHAR(11) NOT NULL,
    budget_id UUID NOT NULL,
    budget_version INTEGER NOT NULL,
    allocation_mode VARCHAR(24) NOT NULL,
    allocation_limit_amount NUMERIC(20, 4),
    allocation_percent NUMERIC(18, 12),
    approved_work_set_revision INTEGER NOT NULL,
    approved_by VARCHAR(128) NOT NULL,
    approved_proof VARCHAR(256) NOT NULL,
    valid_from DATE NOT NULL,
    valid_until DATE,
    binding_hash VARCHAR(71) NOT NULL,
    state VARCHAR(16) NOT NULL,
    business_operation_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (
        tenant_id, company_id, project_id, binding_id, binding_version
    ),
    CONSTRAINT ux_eos_project_budget_hash UNIQUE (
        tenant_id, company_id, binding_hash
    ),
    CONSTRAINT ux_eos_project_budget_operation UNIQUE (
        tenant_id, business_operation_id
    ),
    CONSTRAINT fk_eos_project_budget_project FOREIGN KEY (
        tenant_id, project_id
    ) REFERENCES eos_project (
        tenant_id, project_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_project_budget_budget FOREIGN KEY (
        tenant_id, company_id, budget_id, budget_version
    ) REFERENCES eos_budget (
        tenant_id, company_id, budget_id, budget_version
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_project_budget_work_set FOREIGN KEY (
        tenant_id, project_id, approved_work_set_revision
    ) REFERENCES eos_project_work_code_set (
        tenant_id, project_id, revision
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_project_budget_operation FOREIGN KEY (
        tenant_id, business_operation_id
    ) REFERENCES eos_business_operation (
        tenant_id, business_operation_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_project_budget_version CHECK (
        binding_version > 0 AND budget_version > 0
    ),
    CONSTRAINT ck_eos_project_budget_code CHECK (
        project_code ~ '^[A-Z0-9]{4}[DMSOIG][0-9]{6}$'
    ),
    CONSTRAINT ck_eos_project_budget_mode CHECK (
        allocation_mode IN ('LIMIT_AMOUNT', 'PERCENTAGE')
    ),
    CONSTRAINT ck_eos_project_budget_value CHECK (
        (
            allocation_mode = 'LIMIT_AMOUNT'
            AND allocation_limit_amount > 0
            AND allocation_percent IS NULL
        ) OR (
            allocation_mode = 'PERCENTAGE'
            AND allocation_limit_amount IS NULL
            AND allocation_percent > 0
            AND allocation_percent <= 1
        )
    ),
    CONSTRAINT ck_eos_project_budget_period CHECK (
        valid_until IS NULL OR valid_until >= valid_from
    ),
    CONSTRAINT ck_eos_project_budget_hash CHECK (
        binding_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_project_budget_state CHECK (state = 'APPROVED')
);

CREATE INDEX IF NOT EXISTS ix_eos_project_budget_current
    ON eos_project_budget_binding (
        tenant_id, company_id, project_id, state, valid_from, valid_until
    );

CREATE INDEX IF NOT EXISTS ix_eos_budget_project_allocations
    ON eos_project_budget_binding (
        tenant_id, company_id, budget_id, budget_version, state
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2542_eos_budget_project_binding',
    'Governed Budget SoR and Project read-only budget binding foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
