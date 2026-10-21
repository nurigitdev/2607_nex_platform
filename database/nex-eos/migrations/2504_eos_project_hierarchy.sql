BEGIN;

CREATE TABLE IF NOT EXISTS eos_project (
    tenant_id VARCHAR(128) NOT NULL,
    project_id UUID NOT NULL,
    project_code VARCHAR(64) NOT NULL,
    name VARCHAR(256) NOT NULL,
    parent_project_id UUID NULL,
    nvt_project_id UUID NULL,
    hierarchy_depth INTEGER NOT NULL,
    status VARCHAR(16) NOT NULL,
    start_date DATE NULL,
    end_date DATE NULL,
    currency VARCHAR(3) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_project PRIMARY KEY (tenant_id, project_id),
    CONSTRAINT ux_eos_project_code UNIQUE (tenant_id, project_code),
    CONSTRAINT fk_eos_project_nvt
        FOREIGN KEY (tenant_id, nvt_project_id)
        REFERENCES eos_nvt_project (tenant_id, nvt_project_id),
    CONSTRAINT fk_eos_project_parent
        FOREIGN KEY (tenant_id, parent_project_id)
        REFERENCES eos_project (tenant_id, project_id),
    CONSTRAINT ck_eos_project_lineage CHECK (
        (parent_project_id IS NULL AND nvt_project_id IS NOT NULL)
        OR (parent_project_id IS NOT NULL AND nvt_project_id IS NULL)
    ),
    CONSTRAINT ck_eos_project_depth CHECK (hierarchy_depth BETWEEN 1 AND 3),
    CONSTRAINT ck_eos_project_status CHECK (status IN ('ACTIVE', 'INACTIVE')),
    CONSTRAINT ck_eos_project_dates CHECK (
        end_date IS NULL OR start_date IS NULL OR end_date >= start_date
    ),
    CONSTRAINT ck_eos_project_version CHECK (version > 0)
);

CREATE INDEX IF NOT EXISTS ix_eos_project_parent
    ON eos_project (tenant_id, parent_project_id);

CREATE INDEX IF NOT EXISTS ix_eos_project_nvt
    ON eos_project (tenant_id, nvt_project_id);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2504_eos_project_hierarchy',
    'NeX-EOS ordinary Project hierarchy foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
