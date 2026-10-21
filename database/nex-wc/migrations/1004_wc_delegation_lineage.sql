BEGIN;

CREATE TABLE IF NOT EXISTS wc_delegation_lineage (
    tenant_id TEXT NOT NULL,
    work_item_id UUID NOT NULL,
    root_work_item_id UUID NOT NULL,
    parent_work_item_id UUID NULL,
    parent_claim_ref UUID NULL,
    parent_claim_generation INTEGER NULL,
    delegating_agent_id UUID NOT NULL,
    delegating_agent_type TEXT NOT NULL
        CHECK (delegating_agent_type IN ('IA', 'CA', 'PA', 'EA')),
    parent_agent_execution_id TEXT NOT NULL,
    delegation_depth INTEGER NOT NULL CHECK (delegation_depth BETWEEN 1 AND 10),
    policy_ref TEXT NOT NULL CHECK (policy_ref ~ '^wc\.delegation\.guard\.[a-z0-9._-]{1,96}$'),
    policy_hash TEXT NOT NULL CHECK (policy_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, work_item_id),
    CONSTRAINT fk_wc_dl_work FOREIGN KEY (tenant_id, work_item_id)
        REFERENCES wc_work_item (tenant_id, work_item_id),
    CONSTRAINT fk_wc_dl_root FOREIGN KEY (tenant_id, root_work_item_id)
        REFERENCES wc_work_item (tenant_id, work_item_id),
    CONSTRAINT fk_wc_dl_parent FOREIGN KEY (tenant_id, parent_work_item_id)
        REFERENCES wc_work_item (tenant_id, work_item_id),
    CONSTRAINT fk_wc_dl_parent_claim FOREIGN KEY (tenant_id, parent_claim_ref)
        REFERENCES wc_claim (tenant_id, claim_id),
    CONSTRAINT ck_wc_dl_parent_shape CHECK (
        (
            parent_work_item_id IS NULL
            AND parent_claim_ref IS NULL
            AND parent_claim_generation IS NULL
            AND delegation_depth = 1
            AND root_work_item_id = work_item_id
        )
        OR
        (
            parent_work_item_id IS NOT NULL
            AND parent_claim_ref IS NOT NULL
            AND parent_claim_generation IS NOT NULL
            AND parent_claim_generation >= 1
            AND delegation_depth BETWEEN 2 AND 10
            AND root_work_item_id <> work_item_id
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_wc_dl_root_depth
    ON wc_delegation_lineage (tenant_id, root_work_item_id, delegation_depth);

CREATE INDEX IF NOT EXISTS ix_wc_dl_parent
    ON wc_delegation_lineage (tenant_id, parent_work_item_id)
    WHERE parent_work_item_id IS NOT NULL;

INSERT INTO schema_migrations (version, description)
VALUES ('1004_wc_delegation_lineage', 'WC immutable delegation lineage foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
