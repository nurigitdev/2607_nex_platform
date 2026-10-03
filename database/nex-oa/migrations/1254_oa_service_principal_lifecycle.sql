BEGIN;

CREATE TABLE IF NOT EXISTS oa_service_principals (
    principal_id TEXT PRIMARY KEY
        CHECK (principal_id ~ '^[a-z][a-z0-9._-]{1,63}$'),
    principal_schema_version TEXT NOT NULL DEFAULT 'oa_service_principal.v1'
        CHECK (principal_schema_version = 'oa_service_principal.v1'),
    service_id TEXT NOT NULL
        CHECK (service_id IN ('nex-oa', 'nex-ag', 'nex-ae-api', 'nex-cx', 'nex-mo')),
    display_name TEXT NOT NULL
        CHECK (char_length(display_name) BETWEEN 1 AND 128),
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED')),
    allowed_audiences JSONB NOT NULL
        CHECK (
            jsonb_typeof(allowed_audiences) = 'array'
            AND jsonb_array_length(allowed_audiences) > 0
        ),
    allowed_scopes JSONB NOT NULL
        CHECK (
            jsonb_typeof(allowed_scopes) = 'array'
            AND jsonb_array_length(allowed_scopes) > 0
        ),
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oa_service_creds (
    credential_id TEXT PRIMARY KEY
        CHECK (credential_id ~ '^[a-z][a-z0-9._-]{1,63}$'),
    credential_schema_version TEXT NOT NULL DEFAULT 'oa_service_credential.v1'
        CHECK (credential_schema_version = 'oa_service_credential.v1'),
    principal_id TEXT NOT NULL REFERENCES oa_service_principals(principal_id),
    secret_hash TEXT NOT NULL CHECK (secret_hash LIKE '$argon2id$%'),
    secret_hint TEXT NOT NULL CHECK (char_length(secret_hint) BETWEEN 1 AND 8),
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'ROTATING', 'REVOKED', 'EXPIRED')),
    issued_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    grace_until TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_oa_service_creds_expiry
        CHECK (expires_at > issued_at),
    CONSTRAINT ck_oa_service_creds_grace
        CHECK (
            grace_until IS NULL
            OR (
                grace_until >= issued_at
                AND grace_until <= issued_at + INTERVAL '24 hours'
            )
        )
);

CREATE INDEX IF NOT EXISTS ix_oa_service_principals_service
    ON oa_service_principals (service_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_oa_service_creds_principal
    ON oa_service_creds (principal_id, status, expires_at);

CREATE INDEX IF NOT EXISTS ix_oa_service_creds_expiry
    ON oa_service_creds (status, expires_at);

INSERT INTO schema_migrations (version, description)
VALUES (
    '1254_oa_service_principal_lifecycle',
    'OA service principal and client credential lifecycle persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
