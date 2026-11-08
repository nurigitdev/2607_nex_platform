BEGIN;

CREATE TABLE IF NOT EXISTS eos_project_member (
    tenant_id VARCHAR(128) NOT NULL,
    project_membership_id UUID NOT NULL,
    project_id UUID NOT NULL,
    subject_id VARCHAR(128) NOT NULL,
    member_role VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_by_subject_id VARCHAR(128) NOT NULL,
    removed_by_subject_id VARCHAR(128) NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_project_member
        PRIMARY KEY (tenant_id, project_membership_id),
    CONSTRAINT ux_eos_project_member_subject
        UNIQUE (tenant_id, project_id, subject_id),
    CONSTRAINT fk_eos_project_member_project
        FOREIGN KEY (tenant_id, project_id)
        REFERENCES eos_project (tenant_id, project_id),
    CONSTRAINT ck_eos_project_member_role CHECK (
        member_role IN ('OWNER', 'MANAGER', 'MEMBER', 'VIEWER')
    ),
    CONSTRAINT ck_eos_project_member_status CHECK (
        status IN ('ACTIVE', 'REMOVED')
    ),
    CONSTRAINT ck_eos_project_member_lifecycle CHECK (
        (
            status = 'ACTIVE'
            AND valid_to IS NULL
            AND removed_by_subject_id IS NULL
        )
        OR
        (
            status = 'REMOVED'
            AND valid_to IS NOT NULL
            AND removed_by_subject_id IS NOT NULL
        )
    ),
    CONSTRAINT ck_eos_project_member_period CHECK (
        valid_to IS NULL OR valid_to >= valid_from
    ),
    CONSTRAINT ck_eos_project_member_version CHECK (version > 0)
);

CREATE INDEX IF NOT EXISTS ix_eos_project_member_project
    ON eos_project_member (tenant_id, project_id, status, member_role);

CREATE INDEX IF NOT EXISTS ix_eos_project_member_subject
    ON eos_project_member (tenant_id, subject_id, status, project_id);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2514_eos_project_member',
    'NeX-EOS tenant-scoped Project membership persistence foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
