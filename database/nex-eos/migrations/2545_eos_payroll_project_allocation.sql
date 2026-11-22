BEGIN;

CREATE TABLE IF NOT EXISTS eos_payroll_project_alloc (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    allocation_id UUID NOT NULL,
    allocation_revision INTEGER NOT NULL,
    payroll_evidence_id UUID NOT NULL,
    effort_snapshot_id UUID NOT NULL,
    plan_id UUID NOT NULL,
    plan_revision INTEGER NOT NULL,
    batch_id UUID NOT NULL,
    basis_kind VARCHAR(32) NOT NULL,
    allocation_status VARCHAR(16) NOT NULL,
    residual_treatment VARCHAR(32) NOT NULL,
    project_effort_units NUMERIC(20, 4) NOT NULL,
    residual_effort_units NUMERIC(20, 4) NOT NULL,
    allocated_total NUMERIC(20, 4) NOT NULL,
    residual_total NUMERIC(20, 4) NOT NULL,
    policy_hash VARCHAR(71) NOT NULL,
    allocation_hash VARCHAR(71) NOT NULL,
    supersedes_allocation_id UUID,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, company_id, allocation_id),
    CONSTRAINT ux_eos_payroll_alloc_revision UNIQUE (
        tenant_id, company_id, batch_id, allocation_revision
    ),
    CONSTRAINT ux_eos_payroll_alloc_hash UNIQUE (
        tenant_id, company_id, allocation_hash
    ),
    CONSTRAINT fk_eos_payroll_alloc_evidence FOREIGN KEY (
        tenant_id, company_id, payroll_evidence_id
    ) REFERENCES eos_payroll_post_evidence (
        tenant_id, company_id, evidence_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_payroll_alloc_snapshot FOREIGN KEY (
        tenant_id, company_id, effort_snapshot_id
    ) REFERENCES eos_labor_effort_snapshot (
        tenant_id, company_id, snapshot_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_payroll_alloc_plan FOREIGN KEY (
        tenant_id, company_id, plan_id, plan_revision
    ) REFERENCES eos_cost_allocation_plan (
        tenant_id, company_id, plan_id, plan_revision
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_payroll_alloc_batch FOREIGN KEY (
        tenant_id, company_id, batch_id
    ) REFERENCES eos_cost_allocation_batch (
        tenant_id, company_id, batch_id
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_eos_payroll_alloc_prior FOREIGN KEY (
        tenant_id, company_id, supersedes_allocation_id
    ) REFERENCES eos_payroll_project_alloc (
        tenant_id, company_id, allocation_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_payroll_alloc_revision CHECK (
        allocation_revision > 0
    ),
    CONSTRAINT ck_eos_payroll_alloc_basis CHECK (
        basis_kind IN ('ACTUAL_APPROVED', 'APPROVED_PLAN_FALLBACK')
    ),
    CONSTRAINT ck_eos_payroll_alloc_status CHECK (
        allocation_status IN ('PROVISIONAL', 'CONFIRMED')
    ),
    CONSTRAINT ck_eos_payroll_alloc_residual CHECK (
        residual_treatment IN (
            'RETAIN_UNALLOCATED',
            'ALLOCATE_INDIRECT_OVERHEAD',
            'OPERATING_PROJECT'
        )
    ),
    CONSTRAINT ck_eos_payroll_alloc_effort CHECK (
        project_effort_units > 0 AND residual_effort_units >= 0
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_payroll_alloc_evidence
    ON eos_payroll_project_alloc (
        tenant_id,
        company_id,
        payroll_evidence_id,
        allocation_revision
    );

ALTER TABLE eos_cost_allocation_adjustment
    ALTER COLUMN original_batch_id DROP NOT NULL,
    ALTER COLUMN original_batch_line_no DROP NOT NULL;

ALTER TABLE eos_cost_allocation_adjustment
    ADD COLUMN IF NOT EXISTS payroll_allocation_id UUID,
    ADD COLUMN IF NOT EXISTS payroll_evidence_id UUID,
    ADD COLUMN IF NOT EXISTS prior_snapshot_id UUID,
    ADD COLUMN IF NOT EXISTS replacement_snapshot_id UUID,
    ADD COLUMN IF NOT EXISTS target_project_id UUID,
    ADD COLUMN IF NOT EXISTS target_project_code VARCHAR(11),
    ADD COLUMN IF NOT EXISTS work_code VARCHAR(32),
    ADD COLUMN IF NOT EXISTS adjustment_kind VARCHAR(32),
    ADD COLUMN IF NOT EXISTS basis_source_ref VARCHAR(256),
    ADD COLUMN IF NOT EXISTS basis_source_hash VARCHAR(71);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_eos_cost_adjustment_project'
          AND conrelid = 'eos_cost_allocation_adjustment'::regclass
    ) THEN
        ALTER TABLE eos_cost_allocation_adjustment
            ADD CONSTRAINT fk_eos_cost_adjustment_project FOREIGN KEY (
                tenant_id, target_project_id
            ) REFERENCES eos_project (
                tenant_id, project_id
            ) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_eos_cost_adjustment_payroll'
          AND conrelid = 'eos_cost_allocation_adjustment'::regclass
    ) THEN
        ALTER TABLE eos_cost_allocation_adjustment
            ADD CONSTRAINT fk_eos_cost_adjustment_payroll FOREIGN KEY (
                tenant_id, company_id, payroll_allocation_id
            ) REFERENCES eos_payroll_project_alloc (
                tenant_id, company_id, allocation_id
            ) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_eos_cost_adjustment_evidence'
          AND conrelid = 'eos_cost_allocation_adjustment'::regclass
    ) THEN
        ALTER TABLE eos_cost_allocation_adjustment
            ADD CONSTRAINT fk_eos_cost_adjustment_evidence FOREIGN KEY (
                tenant_id, company_id, payroll_evidence_id
            ) REFERENCES eos_payroll_post_evidence (
                tenant_id, company_id, evidence_id
            ) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_eos_cost_adjustment_prior_snap'
          AND conrelid = 'eos_cost_allocation_adjustment'::regclass
    ) THEN
        ALTER TABLE eos_cost_allocation_adjustment
            ADD CONSTRAINT fk_eos_cost_adjustment_prior_snap FOREIGN KEY (
                tenant_id, company_id, prior_snapshot_id
            ) REFERENCES eos_labor_effort_snapshot (
                tenant_id, company_id, snapshot_id
            ) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_eos_cost_adjustment_repl_snap'
          AND conrelid = 'eos_cost_allocation_adjustment'::regclass
    ) THEN
        ALTER TABLE eos_cost_allocation_adjustment
            ADD CONSTRAINT fk_eos_cost_adjustment_repl_snap FOREIGN KEY (
                tenant_id, company_id, replacement_snapshot_id
            ) REFERENCES eos_labor_effort_snapshot (
                tenant_id, company_id, snapshot_id
            ) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_eos_cost_adjustment_payroll'
          AND conrelid = 'eos_cost_allocation_adjustment'::regclass
    ) THEN
        ALTER TABLE eos_cost_allocation_adjustment
            ADD CONSTRAINT ck_eos_cost_adjustment_payroll CHECK (
                payroll_allocation_id IS NULL OR (
                    payroll_evidence_id IS NOT NULL
                    AND prior_snapshot_id IS NOT NULL
                    AND replacement_snapshot_id IS NOT NULL
                    AND target_project_id IS NOT NULL
                    AND target_project_code IS NOT NULL
                    AND adjustment_kind IN (
                        'PROVISIONAL_TO_ACTUAL', 'ACTUAL_CORRECTION'
                    )
                    AND basis_source_ref IS NOT NULL
                    AND basis_source_hash IS NOT NULL
                )
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_eos_cost_adjustment_payroll
    ON eos_cost_allocation_adjustment (
        tenant_id,
        company_id,
        payroll_evidence_id,
        created_at,
        adjustment_id
    )
    WHERE payroll_allocation_id IS NOT NULL;

ALTER TABLE eos_project_pnl_component
    DROP CONSTRAINT IF EXISTS ck_eos_project_pnl_component_semantics;
ALTER TABLE eos_project_pnl_component
    ADD CONSTRAINT ck_eos_project_pnl_component_semantics CHECK (
        (classification = 'POSTED_REVENUE' AND rollup_class = 'REVENUE' AND confirmed)
        OR (
            classification = 'POSTED_DIRECT_COST'
            AND rollup_class = 'DIRECT_COST' AND confirmed
        )
        OR (
            classification IN (
                'POSTED_ALLOCATED_COST', 'POSTED_LABOR_ALLOCATED',
                'LABOR_ADJUSTMENT'
            )
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
                'MATERIAL_VARIANCE', 'FX_REALIZED_GAIN_LOSS',
                'FX_UNREALIZED_GAIN_LOSS'
            )
            AND rollup_class = 'ADJUSTMENT' AND confirmed
        )
    );

DROP TRIGGER IF EXISTS trg_eos_payroll_alloc_immutable
    ON eos_payroll_project_alloc;
CREATE TRIGGER trg_eos_payroll_alloc_immutable
    BEFORE UPDATE OR DELETE ON eos_payroll_project_alloc
    FOR EACH ROW EXECUTE FUNCTION eos_reject_payroll_labor_mutation();

DROP TRIGGER IF EXISTS trg_eos_cost_adjustment_immutable
    ON eos_cost_allocation_adjustment;
CREATE TRIGGER trg_eos_cost_adjustment_immutable
    BEFORE UPDATE OR DELETE ON eos_cost_allocation_adjustment
    FOR EACH ROW EXECUTE FUNCTION eos_reject_payroll_labor_mutation();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2545_eos_payroll_project_allocation',
    'Payroll Project allocation, residual labor, and append-only adjustment'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
