BEGIN;

CREATE TABLE IF NOT EXISTS eos_pnl_privacy_guard (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    subject_id VARCHAR(128) NOT NULL,
    project_id UUID NOT NULL,
    period_id UUID NOT NULL,
    projection_id UUID NOT NULL,
    projection_version INTEGER NOT NULL,
    privacy_fingerprint VARCHAR(71) NOT NULL,
    population_floor INTEGER NOT NULL,
    minimum_population INTEGER NOT NULL,
    payroll_component_count INTEGER NOT NULL,
    authorization_decision_hash VARCHAR(71) NOT NULL,
    admitted_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (
        tenant_id, company_id, subject_id, project_id, period_id
    ),
    CONSTRAINT fk_eos_pnl_privacy_projection FOREIGN KEY (
        tenant_id, company_id, projection_id
    ) REFERENCES eos_project_pnl_projection (
        tenant_id, company_id, projection_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_eos_pnl_privacy_version CHECK (projection_version > 0),
    CONSTRAINT ck_eos_pnl_privacy_population CHECK (
        population_floor > 0
        AND minimum_population > 0
        AND population_floor >= minimum_population
    ),
    CONSTRAINT ck_eos_pnl_privacy_components CHECK (
        payroll_component_count > 0
    ),
    CONSTRAINT ck_eos_pnl_privacy_hashes CHECK (
        privacy_fingerprint ~ '^sha256:[0-9a-f]{64}$'
        AND authorization_decision_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_pnl_privacy_project
    ON eos_pnl_privacy_guard (
        tenant_id, company_id, project_id, period_id
    );

CREATE OR REPLACE FUNCTION eos_reject_pnl_privacy_guard_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'eos_pnl_privacy_guard is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_eos_pnl_privacy_guard_immutable
    ON eos_pnl_privacy_guard;
CREATE TRIGGER trg_eos_pnl_privacy_guard_immutable
    BEFORE UPDATE OR DELETE ON eos_pnl_privacy_guard
    FOR EACH ROW EXECUTE FUNCTION eos_reject_pnl_privacy_guard_mutation();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2548_eos_pnl_privacy_guard',
    'Project P&L payroll privacy and difference-attack guard admission'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
