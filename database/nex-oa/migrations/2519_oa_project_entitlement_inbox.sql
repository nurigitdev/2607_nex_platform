BEGIN;

ALTER TABLE oa_project_grant
    DROP CONSTRAINT IF EXISTS ux_oa_project_grant_event;

CREATE INDEX IF NOT EXISTS ix_oa_project_grant_event
    ON oa_project_grant (tenant_id, source_event_id);

CREATE TABLE IF NOT EXISTS oa_project_entitlement_inbox (
    tenant_id TEXT NOT NULL REFERENCES oa_tenants(tenant_id),
    event_id UUID NOT NULL,
    project_code TEXT NOT NULL
        CHECK (project_code ~ '^[A-Z0-9]{4}[DMSOIG][0-9]{6}$'),
    source_project_id UUID NOT NULL,
    source_version BIGINT NOT NULL CHECK (source_version > 0),
    event_payload_hash TEXT NOT NULL
        CHECK (event_payload_hash ~ '^sha256:[0-9a-f]{64}$'),
    event_payload JSONB NOT NULL,
    inbox_state TEXT NOT NULL CHECK (inbox_state = 'APPLIED'),
    received_at TIMESTAMPTZ NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, event_id),
    CONSTRAINT ux_oa_project_entitlement_version
        UNIQUE (tenant_id, project_code, source_version)
);

CREATE INDEX IF NOT EXISTS ix_oa_project_entitlement_project
    ON oa_project_entitlement_inbox (
        tenant_id, project_code, source_version DESC
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2519_oa_project_entitlement_inbox',
    'OA Project entitlement event inbox and exact snapshot admission'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
