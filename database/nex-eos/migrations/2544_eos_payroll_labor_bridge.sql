BEGIN;

CREATE TABLE IF NOT EXISTS eos_payroll_post_evidence (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    evidence_id UUID NOT NULL,
    payroll_run_id VARCHAR(128) NOT NULL,
    payroll_period_start DATE NOT NULL,
    payroll_period_end DATE NOT NULL,
    revision INTEGER NOT NULL,
    pool_id UUID NOT NULL,
    journal_id UUID NOT NULL,
    journal_line_no INTEGER NOT NULL,
    period_id UUID NOT NULL,
    eligible_component_id VARCHAR(128) NOT NULL,
    payroll_component_class VARCHAR(32) NOT NULL,
    organization_ref VARCHAR(256),
    account_id UUID NOT NULL,
    eligible_amount_functional NUMERIC(20, 4) NOT NULL,
    functional_currency VARCHAR(3) NOT NULL,
    payroll_source_ref VARCHAR(256) NOT NULL,
    payroll_source_hash VARCHAR(71) NOT NULL,
    approval_ref VARCHAR(256) NOT NULL,
    approval_hash VARCHAR(71) NOT NULL,
    posting_mapping_hash VARCHAR(71) NOT NULL,
    reconciliation_state VARCHAR(16) NOT NULL,
    privacy_class VARCHAR(32) NOT NULL,
    evidence_hash VARCHAR(71) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, company_id, evidence_id),
    CONSTRAINT ux_eos_payroll_post_identity UNIQUE (
        tenant_id, company_id, payroll_run_id, revision, pool_id
    ),
    CONSTRAINT ux_eos_payroll_post_hash UNIQUE (
        tenant_id, company_id, evidence_hash
    ),
    CONSTRAINT fk_eos_payroll_post_pool FOREIGN KEY (
        tenant_id, company_id, pool_id
    ) REFERENCES eos_cost_source_pool (
        tenant_id, company_id, pool_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_payroll_post_period FOREIGN KEY (
        tenant_id, company_id, period_id
    ) REFERENCES eos_accounting_period (
        tenant_id, company_id, period_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_payroll_post_revision CHECK (revision > 0),
    CONSTRAINT ck_eos_payroll_post_period CHECK (
        payroll_period_end >= payroll_period_start
    ),
    CONSTRAINT ck_eos_payroll_post_line CHECK (journal_line_no > 0),
    CONSTRAINT ck_eos_payroll_post_amount CHECK (
        eligible_amount_functional <> 0
    ),
    CONSTRAINT ck_eos_payroll_post_component CHECK (
        payroll_component_class IN (
            'BASE_SALARY', 'OVERTIME', 'BONUS_INCENTIVE',
            'EMPLOYER_INSURANCE', 'EMPLOYER_TAX', 'WELFARE_BENEFIT',
            'PAID_NON_PRODUCTIVE', 'CORRECTION_REVERSAL', 'OTHER_APPROVED'
        )
    ),
    CONSTRAINT ck_eos_payroll_post_currency CHECK (
        functional_currency ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT ck_eos_payroll_post_hashes CHECK (
        payroll_source_hash ~ '^sha256:[0-9a-f]{64}$'
        AND approval_hash ~ '^sha256:[0-9a-f]{64}$'
        AND posting_mapping_hash ~ '^sha256:[0-9a-f]{64}$'
        AND evidence_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_payroll_post_reconcile CHECK (
        reconciliation_state IN ('VERIFIED', 'PENDING', 'BLOCKED')
    ),
    CONSTRAINT ck_eos_payroll_post_privacy CHECK (
        privacy_class = 'PAYROLL_AGGREGATE'
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_payroll_post_period
    ON eos_payroll_post_evidence (
        tenant_id, company_id, payroll_period_end, payroll_run_id
    );

CREATE TABLE IF NOT EXISTS eos_labor_effort_snapshot (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    snapshot_id UUID NOT NULL,
    effort_period_start DATE NOT NULL,
    effort_period_end DATE NOT NULL,
    revision INTEGER NOT NULL,
    basis_kind VARCHAR(32) NOT NULL,
    effort_unit VARCHAR(16) NOT NULL,
    source_ref VARCHAR(256) NOT NULL,
    source_hash VARCHAR(71) NOT NULL,
    evidence_cutoff_at TIMESTAMPTZ NOT NULL,
    approval_ref VARCHAR(256) NOT NULL,
    approval_hash VARCHAR(71) NOT NULL,
    state VARCHAR(16) NOT NULL,
    approved_at TIMESTAMPTZ NOT NULL,
    privacy_class VARCHAR(32) NOT NULL,
    snapshot_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, company_id, snapshot_id),
    CONSTRAINT ux_eos_labor_snapshot_source UNIQUE (
        tenant_id, company_id, source_ref, revision
    ),
    CONSTRAINT ux_eos_labor_snapshot_hash UNIQUE (
        tenant_id, company_id, snapshot_hash
    ),
    CONSTRAINT fk_eos_labor_snapshot_company FOREIGN KEY (
        tenant_id, company_id
    ) REFERENCES eos_legal_entity (
        tenant_id, company_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_labor_snapshot_revision CHECK (revision > 0),
    CONSTRAINT ck_eos_labor_snapshot_period CHECK (
        effort_period_end >= effort_period_start
    ),
    CONSTRAINT ck_eos_labor_snapshot_basis CHECK (
        basis_kind IN ('ACTUAL_APPROVED', 'APPROVED_PLAN_FALLBACK')
    ),
    CONSTRAINT ck_eos_labor_snapshot_unit CHECK (
        effort_unit IN ('MAN_DAY', 'HOUR')
    ),
    CONSTRAINT ck_eos_labor_snapshot_hashes CHECK (
        source_hash ~ '^sha256:[0-9a-f]{64}$'
        AND approval_hash ~ '^sha256:[0-9a-f]{64}$'
        AND snapshot_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_labor_snapshot_state CHECK (
        state IN ('APPROVED', 'SUPERSEDED', 'REVOKED')
    ),
    CONSTRAINT ck_eos_labor_snapshot_privacy CHECK (
        privacy_class = 'LABOR_AGGREGATE'
    ),
    CONSTRAINT ck_eos_labor_snapshot_approval_time CHECK (
        approved_at >= evidence_cutoff_at
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_labor_snapshot_period
    ON eos_labor_effort_snapshot (
        tenant_id, company_id, effort_period_end, state
    );

CREATE TABLE IF NOT EXISTS eos_labor_effort_line (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    snapshot_id UUID NOT NULL,
    line_no INTEGER NOT NULL,
    project_id UUID NOT NULL,
    project_code VARCHAR(11) NOT NULL,
    work_code VARCHAR(16),
    organization_ref VARCHAR(256),
    grade_band VARCHAR(64),
    cost_cohort VARCHAR(64),
    effort_units NUMERIC(16, 4) NOT NULL,
    population_count INTEGER NOT NULL,
    minimum_population INTEGER NOT NULL,
    ordinary_view_suppressed BOOLEAN NOT NULL,
    work_assignment_id UUID,
    basis_source_ref VARCHAR(256) NOT NULL,
    basis_source_hash VARCHAR(71) NOT NULL,
    line_hash VARCHAR(71) NOT NULL,
    PRIMARY KEY (tenant_id, company_id, snapshot_id, line_no),
    CONSTRAINT ux_eos_labor_effort_line_hash UNIQUE (
        tenant_id, company_id, snapshot_id, line_hash
    ),
    CONSTRAINT fk_eos_labor_effort_snapshot FOREIGN KEY (
        tenant_id, company_id, snapshot_id
    ) REFERENCES eos_labor_effort_snapshot (
        tenant_id, company_id, snapshot_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_labor_effort_project FOREIGN KEY (
        tenant_id, project_id
    ) REFERENCES eos_project (
        tenant_id, project_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_labor_effort_assignment FOREIGN KEY (
        tenant_id, work_assignment_id
    ) REFERENCES eos_project_work_assignment (
        tenant_id, assignment_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_labor_effort_line CHECK (line_no > 0),
    CONSTRAINT ck_eos_labor_effort_code CHECK (
        project_code ~ '^[A-Z0-9]{4}[DMSOIG][0-9]{6}$'
        AND (work_code IS NULL OR work_code ~ '^FL[0-9]{7}$')
    ),
    CONSTRAINT ck_eos_labor_effort_units CHECK (effort_units > 0),
    CONSTRAINT ck_eos_labor_effort_population CHECK (
        population_count > 0 AND minimum_population > 0
    ),
    CONSTRAINT ck_eos_labor_effort_suppression CHECK (
        ordinary_view_suppressed = (population_count < minimum_population)
    ),
    CONSTRAINT ck_eos_labor_effort_hashes CHECK (
        basis_source_hash ~ '^sha256:[0-9a-f]{64}$'
        AND line_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_labor_effort_project
    ON eos_labor_effort_line (
        tenant_id, company_id, project_id, work_code
    );

CREATE OR REPLACE FUNCTION eos_reject_payroll_labor_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Payroll/labor evidence is append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_eos_payroll_post_immutable
    ON eos_payroll_post_evidence;
CREATE TRIGGER trg_eos_payroll_post_immutable
    BEFORE UPDATE OR DELETE ON eos_payroll_post_evidence
    FOR EACH ROW EXECUTE FUNCTION eos_reject_payroll_labor_mutation();

DROP TRIGGER IF EXISTS trg_eos_labor_snapshot_immutable
    ON eos_labor_effort_snapshot;
CREATE TRIGGER trg_eos_labor_snapshot_immutable
    BEFORE UPDATE OR DELETE ON eos_labor_effort_snapshot
    FOR EACH ROW EXECUTE FUNCTION eos_reject_payroll_labor_mutation();

DROP TRIGGER IF EXISTS trg_eos_labor_line_immutable
    ON eos_labor_effort_line;
CREATE TRIGGER trg_eos_labor_line_immutable
    BEFORE UPDATE OR DELETE ON eos_labor_effort_line
    FOR EACH ROW EXECUTE FUNCTION eos_reject_payroll_labor_mutation();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2544_eos_payroll_labor_bridge',
    'Privacy-preserving PayrollPostingEvidence and LaborEffortSnapshot bridge'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
