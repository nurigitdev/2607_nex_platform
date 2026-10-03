BEGIN;

CREATE TABLE IF NOT EXISTS oa_fed_providers (
    provider_id TEXT PRIMARY KEY
        CHECK (provider_id ~ '^[a-z][a-z0-9._-]{1,63}$'),
    provider_schema_version TEXT NOT NULL DEFAULT 'oa_fed_provider.v1'
        CHECK (provider_schema_version = 'oa_fed_provider.v1'),
    issuer TEXT NOT NULL UNIQUE,
    client_id TEXT NOT NULL CHECK (char_length(client_id) BETWEEN 1 AND 255),
    discovery_url TEXT NOT NULL,
    display_name TEXT NOT NULL
        CHECK (char_length(display_name) BETWEEN 1 AND 120),
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED')),
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_oa_fed_provider_https
        CHECK (issuer LIKE 'https://%' AND discovery_url LIKE 'https://%')
);

CREATE TABLE IF NOT EXISTS oa_fed_identities (
    provider_id TEXT NOT NULL REFERENCES oa_fed_providers(provider_id),
    external_subject_digest CHAR(64) NOT NULL
        CHECK (external_subject_digest ~ '^[a-f0-9]{64}$'),
    identity_schema_version TEXT NOT NULL DEFAULT 'oa_fed_identity.v1'
        CHECK (identity_schema_version = 'oa_fed_identity.v1'),
    tenant_id TEXT NOT NULL,
    subject_ref_type TEXT NOT NULL DEFAULT 'oa.user'
        CHECK (subject_ref_type = 'oa.user'),
    subject_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED')),
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider_id, external_subject_digest),
    CONSTRAINT fk_oa_fed_identity_subject
        FOREIGN KEY (tenant_id, subject_ref_type, subject_id)
        REFERENCES oa_subjects (tenant_id, subject_ref_type, subject_id),
    CONSTRAINT uq_oa_fed_identity_subject
        UNIQUE (provider_id, tenant_id, subject_id)
);

CREATE INDEX IF NOT EXISTS ix_oa_fed_providers_status
    ON oa_fed_providers (status, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_oa_fed_identities_subject
    ON oa_fed_identities (tenant_id, subject_id, status);

INSERT INTO schema_migrations (version, description)
VALUES (
    '1284_oa_federated_identity',
    'OA federated provider trust and exact subject digest identity links'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
