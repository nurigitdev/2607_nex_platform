BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cx_gen_admissions (
    admission_id TEXT PRIMARY KEY,
    admission_schema_version TEXT NOT NULL
        CHECK (admission_schema_version = 'cx_generation_admission.v1'),
    tenant_ref_type TEXT NOT NULL CHECK (tenant_ref_type = 'oa.tenant'),
    tenant_ref_id TEXT NOT NULL CHECK (
        tenant_ref_id <> '' AND char_length(tenant_ref_id) <= 128
    ),
    owner_subject_ref_type TEXT NOT NULL CHECK (
        owner_subject_ref_type = 'oa.user'
    ),
    owner_subject_ref_id TEXT NOT NULL CHECK (
        owner_subject_ref_id <> ''
        AND char_length(owner_subject_ref_id) <= 128
    ),
    idempotency_key_hash TEXT NOT NULL
        CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    execution_request_hash TEXT NOT NULL
        CHECK (execution_request_hash ~ '^[0-9a-f]{64}$'),
    cx_generation_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL
        CHECK (status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED')),
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    lease_expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    CONSTRAINT ux_cx_gen_adm_owner_key UNIQUE (
        tenant_ref_id,
        owner_subject_ref_id,
        idempotency_key_hash
    ),
    CONSTRAINT ck_cx_gen_adm_terminal CHECK (
        (status = 'IN_PROGRESS' AND completed_at IS NULL)
        OR (status IN ('COMPLETED', 'FAILED') AND completed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_cx_gen_adm_lease
    ON cx_gen_admissions (lease_expires_at)
    WHERE status = 'IN_PROGRESS';

INSERT INTO schema_migrations (version, description)
VALUES (
    '0966_cx_generation_admissions',
    'CX owner-scoped grounded generation idempotency admission'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
