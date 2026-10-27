BEGIN;

CREATE TABLE IF NOT EXISTS wa_work_asset (
    tenant_id TEXT NOT NULL,
    work_asset_id UUID NOT NULL,
    asset_type TEXT NOT NULL
        CHECK (asset_type IN ('AGENT_EXECUTION_RESULT', 'HUMAN_OWNED_ARTIFACT')),
    actor_type TEXT NOT NULL CHECK (actor_type IN ('HUMAN', 'AGENT')),
    actor_ref TEXT NOT NULL,
    agent_type_snapshot TEXT
        CHECK (
            agent_type_snapshot IS NULL
            OR agent_type_snapshot IN ('IA', 'CA', 'PA', 'EA')
        ),
    project_ref UUID,
    occurred_at TIMESTAMPTZ NOT NULL,
    classification TEXT NOT NULL
        CHECK (classification IN ('INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')),
    asset_status TEXT NOT NULL
        CHECK (asset_status IN ('ACTIVE', 'SUPERSEDED', 'INVALIDATED')),
    asset_hash TEXT NOT NULL
        CHECK (asset_hash ~ '^sha256:[0-9a-f]{64}$'),
    version INTEGER NOT NULL CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, work_asset_id)
);

CREATE INDEX IF NOT EXISTS ix_wa_work_asset_project_occurred
    ON wa_work_asset (tenant_id, project_ref, occurred_at DESC)
    WHERE project_ref IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_wa_work_asset_actor_occurred
    ON wa_work_asset (tenant_id, actor_type, actor_ref, occurred_at DESC);

CREATE INDEX IF NOT EXISTS ix_wa_work_asset_status
    ON wa_work_asset (tenant_id, asset_status, occurred_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('2604_wa_work_asset', 'WA WorkAsset persistence')
ON CONFLICT (version) DO NOTHING;

COMMIT;
