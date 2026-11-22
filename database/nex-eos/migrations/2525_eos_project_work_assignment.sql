BEGIN;

CREATE TABLE IF NOT EXISTS eos_project_work_assignment (
    tenant_id VARCHAR(128) NOT NULL,
    assignment_id UUID NOT NULL,
    project_id UUID NOT NULL,
    work_set_id UUID NOT NULL,
    work_set_revision INTEGER NOT NULL,
    work_code_id VARCHAR(16) NOT NULL,
    performer_kind VARCHAR(16) NOT NULL,
    subject_ref VARCHAR(128) NOT NULL,
    performer_authority_hash VARCHAR(71) NOT NULL,
    assignment_scope VARCHAR(16) NOT NULL,
    planned_man_days NUMERIC(12, 4) NOT NULL,
    planned_grade_id VARCHAR(64) NOT NULL,
    grade_policy_ref VARCHAR(256) NOT NULL,
    grade_policy_hash VARCHAR(71) NOT NULL,
    valid_from DATE NOT NULL,
    valid_until DATE NULL,
    approved_proof_hash VARCHAR(71) NOT NULL,
    approved_by_subject_id VARCHAR(128) NOT NULL,
    assignment_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_project_work_assignment
        PRIMARY KEY (tenant_id, assignment_id),
    CONSTRAINT fk_eos_project_assignment_code FOREIGN KEY (
        tenant_id, project_id, work_set_id, work_set_revision, work_code_id
    ) REFERENCES eos_project_work_code_entry (
        tenant_id, project_id, work_set_id, work_set_revision, work_code_id
    ),
    CONSTRAINT ux_eos_project_assignment_hash
        UNIQUE (tenant_id, assignment_hash),
    CONSTRAINT ck_eos_project_assignment_revision
        CHECK (work_set_revision > 0),
    CONSTRAINT ck_eos_project_assignment_performer
        CHECK (performer_kind IN ('HUMAN', 'AGENT')),
    CONSTRAINT ck_eos_project_assignment_scope
        CHECK (assignment_scope IN ('EXECUTE', 'REVIEW', 'REPORT')),
    CONSTRAINT ck_eos_project_assignment_man_days
        CHECK (planned_man_days > 0),
    CONSTRAINT ck_eos_project_assignment_period
        CHECK (valid_until IS NULL OR valid_until >= valid_from),
    CONSTRAINT ck_eos_project_assignment_hashes CHECK (
        grade_policy_hash ~ '^sha256:[0-9a-f]{64}$'
        AND performer_authority_hash ~ '^sha256:[0-9a-f]{64}$'
        AND approved_proof_hash ~ '^sha256:[0-9a-f]{64}$'
        AND assignment_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_project_assignment_project
    ON eos_project_work_assignment (
        tenant_id, project_id, valid_from, valid_until, work_code_id
    );

CREATE INDEX IF NOT EXISTS ix_eos_project_assignment_subject
    ON eos_project_work_assignment (
        tenant_id, subject_ref, performer_kind, valid_from, valid_until
    );

CREATE OR REPLACE FUNCTION eos_guard_project_assignment_overlap()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            NEW.tenant_id || ':' || NEW.project_id::TEXT || ':' ||
            NEW.performer_kind || ':' || NEW.subject_ref || ':' ||
            NEW.work_code_id,
            0
        )
    );
    IF EXISTS (
        SELECT 1
        FROM eos_project_work_assignment existing
        WHERE existing.tenant_id = NEW.tenant_id
          AND existing.project_id = NEW.project_id
          AND existing.performer_kind = NEW.performer_kind
          AND existing.subject_ref = NEW.subject_ref
          AND existing.work_code_id = NEW.work_code_id
          AND existing.valid_from <= COALESCE(NEW.valid_until, 'infinity'::DATE)
          AND COALESCE(existing.valid_until, 'infinity'::DATE) >= NEW.valid_from
    ) THEN
        RAISE EXCEPTION 'overlapping Project WorkAssignment is not allowed'
            USING ERRCODE = '23P01';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION eos_reject_project_assignment_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Project WorkAssignment history is immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_eos_project_assignment_overlap
BEFORE INSERT ON eos_project_work_assignment
FOR EACH ROW EXECUTE FUNCTION eos_guard_project_assignment_overlap();

CREATE TRIGGER trg_eos_project_assignment_immutable
BEFORE UPDATE OR DELETE ON eos_project_work_assignment
FOR EACH ROW EXECUTE FUNCTION eos_reject_project_assignment_mutation();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2525_eos_project_work_assignment',
    'Project WorkAssignment and grade-based Man-Day planning boundary'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
