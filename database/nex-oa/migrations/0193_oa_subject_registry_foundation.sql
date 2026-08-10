BEGIN;

CREATE TABLE IF NOT EXISTS oa_tenants (
    tenant_id TEXT PRIMARY KEY
        CHECK (tenant_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    tenant_ref_type TEXT NOT NULL DEFAULT 'oa.tenant'
        CHECK (tenant_ref_type = 'oa.tenant'),
    display_name TEXT NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 120),
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED', 'DELETED')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oa_subjects (
    tenant_id TEXT NOT NULL REFERENCES oa_tenants(tenant_id),
    subject_id TEXT NOT NULL
        CHECK (subject_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    subject_ref_type TEXT NOT NULL DEFAULT 'oa.user'
        CHECK (subject_ref_type = 'oa.user'),
    display_name TEXT NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 120),
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED', 'DELETED')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, subject_ref_type, subject_id)
);

CREATE INDEX IF NOT EXISTS ix_oa_tenants_status_updated
    ON oa_tenants (status, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_oa_subjects_tenant_status_updated
    ON oa_subjects (tenant_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_oa_subjects_subject_ref
    ON oa_subjects (subject_ref_type, subject_id);

INSERT INTO schema_migrations (version, description)
VALUES ('0193_oa_subject_registry_foundation', 'OA stable tenant and user subject registry foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
