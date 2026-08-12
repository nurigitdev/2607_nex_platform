BEGIN;

CREATE TABLE IF NOT EXISTS oa_local_credentials (
    credential_id TEXT PRIMARY KEY,
    credential_schema_version TEXT NOT NULL DEFAULT 'oa_local_credential.v1'
        CHECK (credential_schema_version = 'oa_local_credential.v1'),
    tenant_id TEXT NOT NULL,
    subject_ref_type TEXT NOT NULL DEFAULT 'oa.user'
        CHECK (subject_ref_type = 'oa.user'),
    subject_id TEXT NOT NULL,
    employee_id TEXT NOT NULL
        CHECK (char_length(employee_id) BETWEEN 1 AND 128),
    normalized_employee_id TEXT NOT NULL
        CHECK (normalized_employee_id ~ '^[a-z0-9][a-z0-9._:-]{0,127}$'),
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'PASSWORD_RESET_REQUIRED', 'LOCKED', 'DISABLED')),
    password_hash TEXT NOT NULL
        CHECK (char_length(password_hash) BETWEEN 64 AND 512),
    password_hash_algorithm TEXT NOT NULL DEFAULT 'pbkdf2_sha256.v1'
        CHECK (password_hash_algorithm IN ('pbkdf2_sha256.v1')),
    failed_attempt_count INTEGER NOT NULL DEFAULT 0
        CHECK (failed_attempt_count >= 0),
    locked_at TIMESTAMPTZ,
    password_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_oa_local_credentials_subject
        FOREIGN KEY (tenant_id, subject_ref_type, subject_id)
        REFERENCES oa_subjects (tenant_id, subject_ref_type, subject_id),
    CONSTRAINT ux_oa_local_credentials_employee
        UNIQUE (tenant_id, normalized_employee_id),
    CONSTRAINT ck_oa_local_credentials_lock
        CHECK (
            (status = 'LOCKED' AND locked_at IS NOT NULL)
            OR (status <> 'LOCKED')
        )
);

CREATE INDEX IF NOT EXISTS ix_oa_local_credentials_subject
    ON oa_local_credentials (subject_ref_type, subject_id);

CREATE INDEX IF NOT EXISTS ix_oa_local_credentials_tenant_status
    ON oa_local_credentials (tenant_id, status, updated_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('0252_oa_local_credential_foundation', 'OA local employee credential registry foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
