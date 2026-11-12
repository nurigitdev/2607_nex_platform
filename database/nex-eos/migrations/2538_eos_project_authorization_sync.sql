BEGIN;

ALTER TABLE eos_project
    ADD COLUMN IF NOT EXISTS authorization_sync_state VARCHAR(16)
        NOT NULL DEFAULT 'FAILED',
    ADD COLUMN IF NOT EXISTS authorization_version BIGINT
        NOT NULL DEFAULT 0;

ALTER TABLE eos_project
    DROP CONSTRAINT IF EXISTS ck_eos_project_authorization_sync,
    DROP CONSTRAINT IF EXISTS ck_eos_project_authorization_version;

ALTER TABLE eos_project
    ADD CONSTRAINT ck_eos_project_authorization_sync CHECK (
        authorization_sync_state IN ('PENDING', 'IN_SYNC', 'FAILED')
    ),
    ADD CONSTRAINT ck_eos_project_authorization_version CHECK (
        authorization_version >= 0
    );

CREATE INDEX IF NOT EXISTS ix_eos_project_authorization_sync
    ON eos_project (
        tenant_id, authorization_sync_state, project_code
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2538_eos_project_authorization_sync',
    'EOS Project authorization snapshot version and OA synchronization state'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
