BEGIN;

CREATE TABLE IF NOT EXISTS eos_project_work_code_set (
    tenant_id VARCHAR(128) NOT NULL,
    project_id UUID NOT NULL,
    work_set_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    catalog_id VARCHAR(128) NOT NULL,
    catalog_version VARCHAR(32) NOT NULL,
    catalog_digest VARCHAR(71) NOT NULL,
    template_ref VARCHAR(256) NOT NULL,
    template_version VARCHAR(32) NOT NULL,
    mandatory_codes_hash VARCHAR(71) NOT NULL,
    approved_proof_hash VARCHAR(71) NOT NULL,
    approved_by_subject_id VARCHAR(128) NOT NULL,
    pm_subject_id VARCHAR(128) NOT NULL,
    pa_agent_id VARCHAR(128) NOT NULL,
    pa_identity_evidence_hash VARCHAR(71) NOT NULL,
    state VARCHAR(16) NOT NULL,
    effective_from DATE NOT NULL,
    work_set_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_project_work_code_set PRIMARY KEY (
        tenant_id, project_id, work_set_id, revision
    ),
    CONSTRAINT fk_eos_project_work_set_project FOREIGN KEY (
        tenant_id, project_id
    ) REFERENCES eos_project (tenant_id, project_id),
    CONSTRAINT ux_eos_project_work_set_revision UNIQUE (
        tenant_id, project_id, revision
    ),
    CONSTRAINT ux_eos_project_work_set_hash UNIQUE (
        tenant_id, work_set_hash
    ),
    CONSTRAINT ck_eos_project_work_set_revision CHECK (revision > 0),
    CONSTRAINT ck_eos_project_work_set_state CHECK (state = 'APPROVED'),
    CONSTRAINT ck_eos_project_work_set_catalog CHECK (
        catalog_id = 'mybee.fl.d12.project-governance'
        AND catalog_version = '1.0.0'
        AND catalog_digest = 'sha256:31e5a24a8a5e62f80fc1571a4a232723a90f9c1b628841ae80df24654848c8ba'
        AND mandatory_codes_hash = 'sha256:f867477ed5983904e1c4a353bf05a4a11ffb56b5fa0299ffd63bbc8cd70bd9a1'
    ),
    CONSTRAINT ck_eos_project_work_set_hashes CHECK (
        catalog_digest ~ '^sha256:[0-9a-f]{64}$'
        AND mandatory_codes_hash ~ '^sha256:[0-9a-f]{64}$'
        AND approved_proof_hash ~ '^sha256:[0-9a-f]{64}$'
        AND pa_identity_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
        AND work_set_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_project_work_set_actor_separation CHECK (
        pm_subject_id <> pa_agent_id
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_project_work_set_current
    ON eos_project_work_code_set (tenant_id, project_id, revision DESC);

CREATE TABLE IF NOT EXISTS eos_project_work_code_entry (
    tenant_id VARCHAR(128) NOT NULL,
    project_id UUID NOT NULL,
    work_set_id UUID NOT NULL,
    work_set_revision INTEGER NOT NULL,
    work_code_id VARCHAR(16) NOT NULL,
    ordinal INTEGER NOT NULL,
    mandatory BOOLEAN NOT NULL,
    CONSTRAINT pk_eos_project_work_code_entry PRIMARY KEY (
        tenant_id, project_id, work_set_id, work_set_revision, work_code_id
    ),
    CONSTRAINT fk_eos_project_work_code_entry_set FOREIGN KEY (
        tenant_id, project_id, work_set_id, work_set_revision
    ) REFERENCES eos_project_work_code_set (
        tenant_id, project_id, work_set_id, revision
    ),
    CONSTRAINT ux_eos_project_work_code_entry_order UNIQUE (
        tenant_id, project_id, work_set_id, work_set_revision, ordinal
    ),
    CONSTRAINT ck_eos_project_work_code_entry_id CHECK (
        work_code_id ~ '^FL[0-9]{7}$'
    ),
    CONSTRAINT ck_eos_project_work_code_entry_order CHECK (ordinal > 0)
);

CREATE OR REPLACE FUNCTION eos_guard_project_work_set_revision()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    latest_revision INTEGER;
    latest_set_id UUID;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.tenant_id || ':' || NEW.project_id::TEXT, 0)
    );
    SELECT revision, work_set_id
      INTO latest_revision, latest_set_id
    FROM eos_project_work_code_set
    WHERE tenant_id = NEW.tenant_id
      AND project_id = NEW.project_id
    ORDER BY revision DESC
    LIMIT 1;

    IF latest_revision IS NULL AND NEW.revision <> 1 THEN
        RAISE EXCEPTION 'first WorkCodeSet revision must be 1'
            USING ERRCODE = '23514';
    ELSIF latest_revision IS NOT NULL AND (
        NEW.revision <> latest_revision + 1
        OR NEW.work_set_id <> latest_set_id
    ) THEN
        RAISE EXCEPTION 'WorkCodeSet revision must advance by one'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION eos_guard_project_work_set_required_codes()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    missing_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO missing_count
    FROM (VALUES
        ('FL0012004'),
        ('FL0012005'),
        ('FL0012006'),
        ('FL0012013'),
        ('FL0012026')
    ) required(work_code_id)
    WHERE NOT EXISTS (
        SELECT 1
        FROM eos_project_work_code_entry entry
        WHERE entry.tenant_id = NEW.tenant_id
          AND entry.project_id = NEW.project_id
          AND entry.work_set_id = NEW.work_set_id
          AND entry.work_set_revision = NEW.revision
          AND entry.work_code_id = required.work_code_id
          AND entry.mandatory IS TRUE
    );
    IF missing_count <> 0 THEN
        RAISE EXCEPTION 'approved WorkCodeSet omits mandatory D12 work codes'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION eos_reject_project_work_set_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'approved Project WorkCodeSet history is immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_eos_project_work_set_revision
BEFORE INSERT ON eos_project_work_code_set
FOR EACH ROW EXECUTE FUNCTION eos_guard_project_work_set_revision();

CREATE CONSTRAINT TRIGGER trg_eos_project_work_set_required_codes
AFTER INSERT ON eos_project_work_code_set
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION eos_guard_project_work_set_required_codes();

CREATE TRIGGER trg_eos_project_work_set_immutable
BEFORE UPDATE OR DELETE ON eos_project_work_code_set
FOR EACH ROW EXECUTE FUNCTION eos_reject_project_work_set_mutation();

CREATE TRIGGER trg_eos_project_work_code_entry_immutable
BEFORE UPDATE OR DELETE ON eos_project_work_code_entry
FOR EACH ROW EXECUTE FUNCTION eos_reject_project_work_set_mutation();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2524_eos_project_work_code_readiness',
    'D12 Project WorkCodeSet immutable revisions and BusinessReady inputs'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
