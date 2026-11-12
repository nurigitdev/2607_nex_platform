BEGIN;

ALTER TABLE eos_project_application
    ADD COLUMN IF NOT EXISTS project_owner_subject_id VARCHAR(128) NULL,
    ADD COLUMN IF NOT EXISTS project_manager_subject_id VARCHAR(128) NULL;

-- Existing applications predate the explicit party contract. Preserve their
-- historical behavior without allowing new v2 requests to omit either party.
UPDATE eos_project_application
SET project_owner_subject_id = applicant_subject_id,
    project_manager_subject_id = applicant_subject_id
WHERE project_owner_subject_id IS NULL
   OR project_manager_subject_id IS NULL;

ALTER TABLE eos_project_application
    ALTER COLUMN project_owner_subject_id SET NOT NULL,
    ALTER COLUMN project_manager_subject_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_eos_project_application_owner
    ON eos_project_application (
        tenant_id, project_owner_subject_id, state, updated_at
    );

CREATE INDEX IF NOT EXISTS ix_eos_project_application_manager
    ON eos_project_application (
        tenant_id, project_manager_subject_id, state, updated_at
    );

CREATE OR REPLACE FUNCTION eos_guard_project_application_lifecycle()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.project_request_code IS DISTINCT FROM OLD.project_request_code
       OR NEW.tenant_code IS DISTINCT FROM OLD.tenant_code
       OR NEW.code_year IS DISTINCT FROM OLD.code_year
       OR NEW.applicant_subject_id IS DISTINCT FROM OLD.applicant_subject_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'Project application identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.state <> OLD.state AND NOT (
        (OLD.state = 'DRAFT' AND NEW.state = 'SUBMITTED')
        OR
        (OLD.state = 'SUBMITTED' AND NEW.state IN ('APPROVED', 'REJECTED'))
    ) THEN
        RAISE EXCEPTION 'Project application state transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.current_revision <> OLD.current_revision
       AND (
           OLD.state <> 'DRAFT'
           OR NEW.state <> 'DRAFT'
           OR NEW.current_revision <> OLD.current_revision + 1
       ) THEN
        RAISE EXCEPTION 'Project application revision transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF (
        NEW.project_owner_subject_id IS DISTINCT FROM OLD.project_owner_subject_id
        OR NEW.project_manager_subject_id IS DISTINCT FROM OLD.project_manager_subject_id
    ) AND (
        OLD.state <> 'DRAFT'
        OR NEW.state <> 'DRAFT'
        OR NEW.current_revision <> OLD.current_revision + 1
    ) THEN
        RAISE EXCEPTION 'Project parties may change only in a new DRAFT revision'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'Project application version must advance by one'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

INSERT INTO schema_migrations (version, description)
VALUES (
    '2536_eos_project_application_parties',
    'Explicit Project owner, manager, and immutable initial membership contract'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
