BEGIN;

CREATE TABLE IF NOT EXISTS oa_user_sessions (
    session_id TEXT PRIMARY KEY,
    session_schema_version TEXT NOT NULL DEFAULT 'oa_user_session.v1'
        CHECK (session_schema_version = 'oa_user_session.v1'),
    tenant_id TEXT NOT NULL,
    subject_ref_type TEXT NOT NULL DEFAULT 'oa.user'
        CHECK (subject_ref_type = 'oa.user'),
    subject_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'EXPIRED', 'REVOKED')),
    issuer TEXT NOT NULL DEFAULT 'nex-oa'
        CHECK (issuer = 'nex-oa'),
    audience TEXT NOT NULL DEFAULT 'nex-ae-api'
        CHECK (audience = 'nex-ae-api'),
    token_use TEXT NOT NULL DEFAULT 'user'
        CHECK (token_use = 'user'),
    scopes JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(scopes) = 'array'),
    roles JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(roles) = 'array'),
    issued_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    auth_time TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_oa_user_sessions_membership
        FOREIGN KEY (tenant_id, subject_ref_type, subject_id)
        REFERENCES oa_tenant_memberships (tenant_id, subject_ref_type, subject_id),
    CONSTRAINT ck_oa_user_sessions_time_order
        CHECK (expires_at > issued_at),
    CONSTRAINT ck_oa_user_sessions_revoked_at
        CHECK (
            (status = 'REVOKED' AND revoked_at IS NOT NULL)
            OR (status <> 'REVOKED' AND revoked_at IS NULL)
        )
);

CREATE INDEX IF NOT EXISTS ix_oa_user_sessions_tenant_status_expires
    ON oa_user_sessions (tenant_id, status, expires_at DESC);

CREATE INDEX IF NOT EXISTS ix_oa_user_sessions_subject_issued
    ON oa_user_sessions (subject_ref_type, subject_id, issued_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('0243_oa_user_session_foundation', 'OA user session issuance persistence foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
