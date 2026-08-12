BEGIN;

CREATE TABLE IF NOT EXISTS oa_tenant_memberships (
    tenant_id TEXT NOT NULL,
    subject_ref_type TEXT NOT NULL DEFAULT 'oa.user'
        CHECK (subject_ref_type = 'oa.user'),
    subject_id TEXT NOT NULL,
    membership_schema_version TEXT NOT NULL DEFAULT 'oa_tenant_membership.v1'
        CHECK (membership_schema_version = 'oa_tenant_membership.v1'),
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED')),
    roles JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(roles) = 'array'),
    scopes JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(scopes) = 'array'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, subject_ref_type, subject_id),
    CONSTRAINT fk_oa_tenant_memberships_subject
        FOREIGN KEY (tenant_id, subject_ref_type, subject_id)
        REFERENCES oa_subjects (tenant_id, subject_ref_type, subject_id)
);

CREATE INDEX IF NOT EXISTS ix_oa_tenant_memberships_status_updated
    ON oa_tenant_memberships (status, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_oa_tenant_memberships_subject
    ON oa_tenant_memberships (subject_ref_type, subject_id);

INSERT INTO schema_migrations (version, description)
VALUES ('0242_oa_tenant_membership_foundation', 'OA tenant membership persistence foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
