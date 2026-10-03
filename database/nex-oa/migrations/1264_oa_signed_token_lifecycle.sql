BEGIN;

CREATE TABLE IF NOT EXISTS oa_signing_keys (
    key_id TEXT PRIMARY KEY
        CHECK (key_id ~ '^[a-z][a-z0-9._-]{1,63}$'),
    signing_key_schema_version TEXT NOT NULL DEFAULT 'oa_signing_key.v1'
        CHECK (signing_key_schema_version = 'oa_signing_key.v1'),
    issuer TEXT NOT NULL DEFAULT 'urn:nex-platform:oa'
        CHECK (issuer = 'urn:nex-platform:oa'),
    algorithm TEXT NOT NULL DEFAULT 'RS256'
        CHECK (algorithm = 'RS256'),
    state TEXT NOT NULL DEFAULT 'PREPUBLISHED'
        CHECK (state IN ('PREPUBLISHED', 'ACTIVE', 'VERIFY_ONLY', 'RETIRED', 'REVOKED')),
    public_jwk JSONB NOT NULL
        CHECK (jsonb_typeof(public_jwk) = 'object')
        CHECK (NOT (public_jwk ?| ARRAY['d', 'p', 'q', 'dp', 'dq', 'qi', 'oth'])),
    private_key_ref TEXT NOT NULL
        CHECK (char_length(private_key_ref) BETWEEN 6 AND 512),
    published_at TIMESTAMPTZ NOT NULL,
    activate_at TIMESTAMPTZ NOT NULL,
    sign_until TIMESTAMPTZ NOT NULL,
    verify_until TIMESTAMPTZ NOT NULL,
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_oa_signing_keys_windows
        CHECK (
            activate_at >= published_at + INTERVAL '330 seconds'
            AND sign_until > activate_at
            AND verify_until >= sign_until + INTERVAL '330 seconds'
        )
);

CREATE TABLE IF NOT EXISTS oa_token_revocations (
    revocation_id TEXT PRIMARY KEY
        CHECK (revocation_id ~ '^[a-z][a-z0-9._-]{1,63}$'),
    revocation_schema_version TEXT NOT NULL DEFAULT 'oa_token_revocation.v1'
        CHECK (revocation_schema_version = 'oa_token_revocation.v1'),
    jti_digest CHAR(64) NOT NULL UNIQUE
        CHECK (jti_digest ~ '^[0-9a-f]{64}$'),
    issuer TEXT NOT NULL DEFAULT 'urn:nex-platform:oa'
        CHECK (issuer = 'urn:nex-platform:oa'),
    subject_ref TEXT NOT NULL CHECK (char_length(subject_ref) BETWEEN 1 AND 256),
    audience TEXT NOT NULL
        CHECK (audience IN ('nex-oa', 'nex-ag', 'nex-ae-api', 'nex-cx', 'nex-mo')),
    token_use TEXT NOT NULL DEFAULT 'service_access'
        CHECK (token_use = 'service_access'),
    reason_code TEXT NOT NULL
        CHECK (reason_code IN ('CREDENTIAL_REVOKED', 'PRINCIPAL_DISABLED', 'KEY_COMPROMISE', 'OPERATOR')),
    revoked_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_oa_token_revocations_expiry
        CHECK (expires_at > revoked_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_oa_signing_keys_active
    ON oa_signing_keys (issuer)
    WHERE state = 'ACTIVE';

CREATE INDEX IF NOT EXISTS ix_oa_signing_keys_state
    ON oa_signing_keys (state, activate_at, verify_until);

CREATE INDEX IF NOT EXISTS ix_oa_token_revocations_expiry
    ON oa_token_revocations (expires_at);

CREATE INDEX IF NOT EXISTS ix_oa_token_revocations_subject
    ON oa_token_revocations (issuer, subject_ref, expires_at);

INSERT INTO schema_migrations (version, description)
VALUES (
    '1264_oa_signed_token_lifecycle',
    'OA signing key metadata and hashed token revocation persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
