BEGIN;

CREATE TABLE IF NOT EXISTS oa_project_grant (
    tenant_id TEXT NOT NULL REFERENCES oa_tenants(tenant_id),
    project_code TEXT NOT NULL
        CHECK (project_code ~ '^[A-Z0-9]{4}[DMSOIG][0-9]{6}$'),
    subject_id TEXT NOT NULL,
    project_role TEXT NOT NULL
        CHECK (project_role IN ('OWNER', 'MANAGER', 'MEMBER', 'VIEWER')),
    grant_status TEXT NOT NULL
        CHECK (grant_status IN ('ACTIVE', 'REVOKED')),
    project_status TEXT NOT NULL
        CHECK (project_status IN ('ACTIVE', 'INACTIVE', 'CLOSING', 'CLOSED')),
    source_project_id UUID NOT NULL,
    source_version BIGINT NOT NULL CHECK (source_version > 0),
    source_event_id UUID NOT NULL,
    source_event_hash TEXT NOT NULL
        CHECK (source_event_hash ~ '^sha256:[0-9a-f]{64}$'),
    granted_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, project_code, subject_id),
    CONSTRAINT ux_oa_project_grant_event UNIQUE (tenant_id, source_event_id),
    CONSTRAINT ck_oa_project_grant_lifecycle CHECK (
        (grant_status = 'ACTIVE' AND revoked_at IS NULL)
        OR (grant_status = 'REVOKED' AND revoked_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_oa_project_grant_subject
    ON oa_project_grant (
        tenant_id, subject_id, grant_status, project_status, project_code
    );

CREATE INDEX IF NOT EXISTS ix_oa_project_grant_resource
    ON oa_project_grant (
        tenant_id, project_code, grant_status, project_role, subject_id
    );

CREATE INDEX IF NOT EXISTS ix_oa_project_grant_source
    ON oa_project_grant (tenant_id, source_project_id, source_version DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2518_oa_project_grant',
    'OA Project-code entitlement projection and decision persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
