BEGIN;

ALTER TABLE eos_project
    ADD COLUMN IF NOT EXISTS project_owner_subject_id VARCHAR(128) NULL,
    ADD COLUMN IF NOT EXISTS project_manager_subject_id VARCHAR(128) NULL;

UPDATE eos_project AS project
SET project_owner_subject_id = application.project_owner_subject_id,
    project_manager_subject_id = application.project_manager_subject_id
FROM eos_project_application AS application
WHERE project.tenant_id = application.tenant_id
  AND project.project_request_code = application.project_request_code
  AND project.origin = 'APPROVED_APPLICATION'
  AND (
      project.project_owner_subject_id IS NULL
      OR project.project_manager_subject_id IS NULL
  );

ALTER TABLE eos_project
    DROP CONSTRAINT IF EXISTS ck_eos_project_approved_parties;

ALTER TABLE eos_project
    ADD CONSTRAINT ck_eos_project_approved_parties CHECK (
        origin = 'LEGACY_DIRECT'
        OR (
            origin = 'APPROVED_APPLICATION'
            AND project_owner_subject_id IS NOT NULL
            AND project_manager_subject_id IS NOT NULL
        )
    ) NOT VALID;

CREATE INDEX IF NOT EXISTS ix_eos_project_owner
    ON eos_project (tenant_id, project_owner_subject_id, status)
    WHERE project_owner_subject_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_eos_project_manager
    ON eos_project (tenant_id, project_manager_subject_id, status)
    WHERE project_manager_subject_id IS NOT NULL;

INSERT INTO schema_migrations (version, description)
VALUES (
    '2537_eos_project_approved_parties',
    'Approved Project owner, manager, and exact membership materialization'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
