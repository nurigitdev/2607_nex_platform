BEGIN;

CREATE TABLE IF NOT EXISTS eos_nvt_project (
    tenant_id VARCHAR(128) NOT NULL,
    nvt_project_id UUID NOT NULL,
    nvt_project_code VARCHAR(64) NOT NULL,
    name VARCHAR(256) NOT NULL,
    status VARCHAR(16) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_nvt_project
        PRIMARY KEY (tenant_id, nvt_project_id),
    CONSTRAINT ux_eos_nvt_project_code
        UNIQUE (tenant_id, nvt_project_code),
    CONSTRAINT ck_eos_nvt_project_status
        CHECK (status IN ('ACTIVE', 'INACTIVE')),
    CONSTRAINT ck_eos_nvt_project_version CHECK (version > 0)
);

CREATE INDEX IF NOT EXISTS ix_eos_nvt_project_status
    ON eos_nvt_project (tenant_id, status, nvt_project_code);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2503_eos_nvt_project',
    'NeX-EOS separate NVTProject business-object foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
