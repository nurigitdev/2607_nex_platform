BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wc_assignment (
    tenant_id TEXT NOT NULL,
    assignment_id UUID NOT NULL,
    work_item_id UUID NOT NULL,
    routing_decision_id UUID NOT NULL,
    agent_id UUID NOT NULL,
    agent_type TEXT NOT NULL CHECK (agent_type IN ('CA', 'PA', 'EA')),
    project_id TEXT NOT NULL,
    claim_generation INTEGER NOT NULL CHECK (claim_generation >= 1),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RELEASED', 'COMPLETED')),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, assignment_id),
    CONSTRAINT fk_wc_assignment_work FOREIGN KEY (tenant_id, work_item_id)
        REFERENCES wc_work_item (tenant_id, work_item_id),
    CONSTRAINT fk_wc_assignment_route FOREIGN KEY (tenant_id, routing_decision_id)
        REFERENCES wc_routing_decision (tenant_id, routing_decision_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_wc_active_assignment
    ON wc_assignment (tenant_id, work_item_id)
    WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS wc_claim (
    tenant_id TEXT NOT NULL,
    claim_id UUID NOT NULL,
    work_item_id UUID NOT NULL,
    assignment_id UUID NOT NULL,
    claim_generation INTEGER NOT NULL CHECK (claim_generation >= 1),
    state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'EXPIRED', 'RELEASED', 'COMPLETED')),
    lease_verifier TEXT NOT NULL CHECK (lease_verifier ~ '^sha256:[0-9a-f]{64}$'),
    lease_expires_at TIMESTAMPTZ NOT NULL,
    authorization_revision_hash TEXT NOT NULL,
    authorized_subject_id TEXT NOT NULL,
    authorization_checked_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, claim_id),
    CONSTRAINT fk_wc_claim_work FOREIGN KEY (tenant_id, work_item_id)
        REFERENCES wc_work_item (tenant_id, work_item_id),
    CONSTRAINT fk_wc_claim_assignment FOREIGN KEY (tenant_id, assignment_id)
        REFERENCES wc_assignment (tenant_id, assignment_id),
    CONSTRAINT ux_wc_claim_generation UNIQUE (tenant_id, work_item_id, claim_generation)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_wc_active_claim
    ON wc_claim (tenant_id, work_item_id)
    WHERE state = 'ACTIVE';

CREATE INDEX IF NOT EXISTS ix_wc_claim_lease_expiry
    ON wc_claim (state, lease_expires_at);

INSERT INTO schema_migrations (version, description)
VALUES ('1001_wc_assignment_claim', 'WC atomic assignment, claim generation, and lease authority')
ON CONFLICT (version) DO NOTHING;

COMMIT;
