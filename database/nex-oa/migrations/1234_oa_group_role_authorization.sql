BEGIN;

CREATE TABLE IF NOT EXISTS oa_roles (
    tenant_id TEXT NOT NULL REFERENCES oa_tenants(tenant_id),
    role_id TEXT NOT NULL
        CHECK (role_id ~ '^[a-z][a-z0-9._-]{1,63}$'),
    role_schema_version TEXT NOT NULL DEFAULT 'oa_role.v1'
        CHECK (role_schema_version = 'oa_role.v1'),
    display_name TEXT NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 128),
    description TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED')),
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    scopes JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(scopes) = 'array'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, role_id)
);

CREATE TABLE IF NOT EXISTS oa_groups (
    tenant_id TEXT NOT NULL REFERENCES oa_tenants(tenant_id),
    group_id TEXT NOT NULL
        CHECK (group_id ~ '^[a-z][a-z0-9._-]{1,63}$'),
    group_schema_version TEXT NOT NULL DEFAULT 'oa_group.v1'
        CHECK (group_schema_version = 'oa_group.v1'),
    display_name TEXT NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 128),
    description TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED')),
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, group_id)
);

CREATE TABLE IF NOT EXISTS oa_group_members (
    tenant_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    subject_ref_type TEXT NOT NULL DEFAULT 'oa.user'
        CHECK (subject_ref_type = 'oa.user'),
    subject_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED')),
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, group_id, subject_id),
    CONSTRAINT fk_oa_group_members_group
        FOREIGN KEY (tenant_id, group_id)
        REFERENCES oa_groups (tenant_id, group_id),
    CONSTRAINT fk_oa_group_members_membership
        FOREIGN KEY (tenant_id, subject_ref_type, subject_id)
        REFERENCES oa_tenant_memberships (tenant_id, subject_ref_type, subject_id)
);

CREATE TABLE IF NOT EXISTS oa_group_roles (
    tenant_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED')),
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, group_id, role_id),
    CONSTRAINT fk_oa_group_roles_group
        FOREIGN KEY (tenant_id, group_id)
        REFERENCES oa_groups (tenant_id, group_id),
    CONSTRAINT fk_oa_group_roles_role
        FOREIGN KEY (tenant_id, role_id)
        REFERENCES oa_roles (tenant_id, role_id)
);

CREATE TABLE IF NOT EXISTS oa_authz_events (
    event_id TEXT PRIMARY KEY,
    event_schema_version TEXT NOT NULL DEFAULT 'oa_authz_event.v1'
        CHECK (event_schema_version = 'oa_authz_event.v1'),
    tenant_id TEXT NOT NULL REFERENCES oa_tenants(tenant_id),
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL
        CHECK (entity_type IN ('ROLE', 'GROUP', 'GROUP_MEMBER', 'GROUP_ROLE')),
    entity_id TEXT NOT NULL,
    subject_id TEXT,
    previous_revision BIGINT NOT NULL CHECK (previous_revision >= 0),
    next_revision BIGINT NOT NULL CHECK (next_revision > previous_revision),
    actor_ref TEXT NOT NULL,
    request_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(details) = 'object'),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_oa_roles_status
    ON oa_roles (tenant_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_oa_groups_status
    ON oa_groups (tenant_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_oa_group_members_subject
    ON oa_group_members (tenant_id, subject_id, status);

CREATE INDEX IF NOT EXISTS ix_oa_group_roles_role
    ON oa_group_roles (tenant_id, role_id, status);

CREATE INDEX IF NOT EXISTS ix_oa_authz_events_tenant_time
    ON oa_authz_events (tenant_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS ix_oa_authz_events_subject_time
    ON oa_authz_events (tenant_id, subject_id, occurred_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '1234_oa_group_role_authorization',
    'OA tenant group, role, assignment, and authorization event persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
