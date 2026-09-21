BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE service_jobs
    ADD COLUMN IF NOT EXISTS tenant_ref_type TEXT,
    ADD COLUMN IF NOT EXISTS tenant_ref_id TEXT,
    ADD COLUMN IF NOT EXISTS owner_subject_ref_type TEXT,
    ADD COLUMN IF NOT EXISTS owner_subject_ref_id TEXT;

ALTER TABLE cx_document_processing_runs
    ADD COLUMN IF NOT EXISTS tenant_ref_type TEXT,
    ADD COLUMN IF NOT EXISTS tenant_ref_id TEXT,
    ADD COLUMN IF NOT EXISTS owner_subject_ref_type TEXT,
    ADD COLUMN IF NOT EXISTS owner_subject_ref_id TEXT;

ALTER TABLE cx_retrieval_packages
    ADD COLUMN IF NOT EXISTS tenant_ref_type TEXT,
    ADD COLUMN IF NOT EXISTS tenant_ref_id TEXT,
    ADD COLUMN IF NOT EXISTS owner_subject_ref_type TEXT,
    ADD COLUMN IF NOT EXISTS owner_subject_ref_id TEXT;

ALTER TABLE cx_remediation_execution_attempts
    ADD COLUMN IF NOT EXISTS tenant_ref_type TEXT,
    ADD COLUMN IF NOT EXISTS tenant_ref_id TEXT,
    ADD COLUMN IF NOT EXISTS owner_subject_ref_type TEXT,
    ADD COLUMN IF NOT EXISTS owner_subject_ref_id TEXT;

CREATE OR REPLACE FUNCTION cx_owner_lineage_is_valid(
    tenant_type TEXT,
    tenant_id TEXT,
    owner_type TEXT,
    owner_id TEXT
)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT
        (
            tenant_type IS NULL
            AND tenant_id IS NULL
            AND owner_type IS NULL
            AND owner_id IS NULL
        )
        OR (
            tenant_type = 'oa.tenant'
            AND tenant_id IS NOT NULL
            AND tenant_id <> ''
            AND char_length(tenant_id) <= 128
            AND owner_type = 'oa.user'
            AND owner_id IS NOT NULL
            AND owner_id <> ''
            AND char_length(owner_id) <= 128
        );
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_service_jobs_owner_lineage'
    ) THEN
        ALTER TABLE service_jobs
            ADD CONSTRAINT ck_service_jobs_owner_lineage
            CHECK (cx_owner_lineage_is_valid(
                tenant_ref_type,
                tenant_ref_id,
                owner_subject_ref_type,
                owner_subject_ref_id
            ));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_cx_proc_runs_owner_lineage'
    ) THEN
        ALTER TABLE cx_document_processing_runs
            ADD CONSTRAINT ck_cx_proc_runs_owner_lineage
            CHECK (cx_owner_lineage_is_valid(
                tenant_ref_type,
                tenant_ref_id,
                owner_subject_ref_type,
                owner_subject_ref_id
            ));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_cx_ret_packages_owner_lineage'
    ) THEN
        ALTER TABLE cx_retrieval_packages
            ADD CONSTRAINT ck_cx_ret_packages_owner_lineage
            CHECK (cx_owner_lineage_is_valid(
                tenant_ref_type,
                tenant_ref_id,
                owner_subject_ref_type,
                owner_subject_ref_id
            ));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_cx_rem_attempts_owner_lineage'
    ) THEN
        ALTER TABLE cx_remediation_execution_attempts
            ADD CONSTRAINT ck_cx_rem_attempts_owner_lineage
            CHECK (cx_owner_lineage_is_valid(
                tenant_ref_type,
                tenant_ref_id,
                owner_subject_ref_type,
                owner_subject_ref_id
            ));
    END IF;
END $$;

UPDATE cx_document_processing_runs AS run
SET tenant_ref_type = content.tenant_ref_type,
    tenant_ref_id = content.tenant_ref_id,
    owner_subject_ref_type = content.owner_subject_ref_type,
    owner_subject_ref_id = content.owner_subject_ref_id
FROM cx_content_objects AS content
WHERE run.document_id = content.content_object_id
  AND run.tenant_ref_id IS NULL;

UPDATE service_jobs AS job
SET tenant_ref_type = content.tenant_ref_type,
    tenant_ref_id = content.tenant_ref_id,
    owner_subject_ref_type = content.owner_subject_ref_type,
    owner_subject_ref_id = content.owner_subject_ref_id
FROM cx_content_objects AS content
WHERE job.subject_type = 'cx.document'
  AND job.subject_id = content.content_object_id::text
  AND job.tenant_ref_id IS NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT evidence.retrieval_package_id
        FROM cx_retrieval_evidence_items AS evidence
        JOIN cx_content_objects AS content
          ON content.content_object_id = evidence.content_object_id
        GROUP BY evidence.retrieval_package_id
        HAVING count(DISTINCT ROW(
            content.tenant_ref_type,
            content.tenant_ref_id,
            content.owner_subject_ref_type,
            content.owner_subject_ref_id
        )) > 1
    ) THEN
        RAISE EXCEPTION 'Existing CX retrieval package mixes owner scopes'
            USING ERRCODE = '23514';
    END IF;
END $$;

WITH owner_candidates AS (
    SELECT DISTINCT
        evidence.retrieval_package_id,
        content.tenant_ref_type,
        content.tenant_ref_id,
        content.owner_subject_ref_type,
        content.owner_subject_ref_id
    FROM cx_retrieval_evidence_items AS evidence
    JOIN cx_content_objects AS content
      ON content.content_object_id = evidence.content_object_id
),
single_owner AS (
    SELECT retrieval_package_id
    FROM owner_candidates
    GROUP BY retrieval_package_id
    HAVING count(*) = 1
)
UPDATE cx_retrieval_packages AS package
SET tenant_ref_type = owner.tenant_ref_type,
    tenant_ref_id = owner.tenant_ref_id,
    owner_subject_ref_type = owner.owner_subject_ref_type,
    owner_subject_ref_id = owner.owner_subject_ref_id
FROM owner_candidates AS owner
JOIN single_owner USING (retrieval_package_id)
WHERE package.retrieval_package_id = owner.retrieval_package_id
  AND package.tenant_ref_id IS NULL;

CREATE OR REPLACE FUNCTION cx_apply_document_owner_lineage()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    SELECT
        content.tenant_ref_type,
        content.tenant_ref_id,
        content.owner_subject_ref_type,
        content.owner_subject_ref_id
    INTO
        NEW.tenant_ref_type,
        NEW.tenant_ref_id,
        NEW.owner_subject_ref_type,
        NEW.owner_subject_ref_id
    FROM cx_content_objects AS content
    WHERE content.content_object_id = NEW.document_id;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tr_cx_proc_runs_apply_owner
    ON cx_document_processing_runs;
CREATE TRIGGER tr_cx_proc_runs_apply_owner
    BEFORE INSERT OR UPDATE OF document_id ON cx_document_processing_runs
    FOR EACH ROW
    EXECUTE FUNCTION cx_apply_document_owner_lineage();

CREATE OR REPLACE FUNCTION cx_apply_job_owner_lineage()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.subject_type = 'cx.document' THEN
        SELECT
            content.tenant_ref_type,
            content.tenant_ref_id,
            content.owner_subject_ref_type,
            content.owner_subject_ref_id
        INTO
            NEW.tenant_ref_type,
            NEW.tenant_ref_id,
            NEW.owner_subject_ref_type,
        NEW.owner_subject_ref_id
    FROM cx_content_objects AS content
    WHERE content.content_object_id::text = NEW.subject_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'CX document job subject does not exist'
                USING ERRCODE = '23503';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tr_cx_jobs_apply_owner ON service_jobs;
CREATE TRIGGER tr_cx_jobs_apply_owner
    BEFORE INSERT OR UPDATE OF subject_type, subject_id ON service_jobs
    FOR EACH ROW
    EXECUTE FUNCTION cx_apply_job_owner_lineage();

CREATE OR REPLACE FUNCTION cx_apply_retrieval_owner_lineage()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    content_owner RECORD;
    package_owner RECORD;
BEGIN
    SELECT
        tenant_ref_type,
        tenant_ref_id,
        owner_subject_ref_type,
        owner_subject_ref_id
    INTO content_owner
    FROM cx_content_objects
    WHERE content_object_id = NEW.content_object_id;

    SELECT
        tenant_ref_type,
        tenant_ref_id,
        owner_subject_ref_type,
        owner_subject_ref_id
    INTO package_owner
    FROM cx_retrieval_packages
    WHERE retrieval_package_id = NEW.retrieval_package_id
    FOR UPDATE;

    IF package_owner.tenant_ref_id IS NULL THEN
        UPDATE cx_retrieval_packages
        SET tenant_ref_type = content_owner.tenant_ref_type,
            tenant_ref_id = content_owner.tenant_ref_id,
            owner_subject_ref_type = content_owner.owner_subject_ref_type,
            owner_subject_ref_id = content_owner.owner_subject_ref_id
        WHERE retrieval_package_id = NEW.retrieval_package_id;
    ELSIF package_owner.tenant_ref_type <> content_owner.tenant_ref_type
       OR package_owner.tenant_ref_id <> content_owner.tenant_ref_id
       OR package_owner.owner_subject_ref_type <> content_owner.owner_subject_ref_type
       OR package_owner.owner_subject_ref_id <> content_owner.owner_subject_ref_id THEN
        RAISE EXCEPTION 'CX retrieval package cannot mix owner scopes'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tr_cx_ret_evidence_apply_owner
    ON cx_retrieval_evidence_items;
CREATE TRIGGER tr_cx_ret_evidence_apply_owner
    AFTER INSERT OR UPDATE OF content_object_id
    ON cx_retrieval_evidence_items
    FOR EACH ROW
    EXECUTE FUNCTION cx_apply_retrieval_owner_lineage();

CREATE TABLE IF NOT EXISTS cx_generation_executions (
    cx_generation_id TEXT PRIMARY KEY,
    record_schema_version TEXT NOT NULL DEFAULT 'cx_generation_execution_record.v1'
        CHECK (record_schema_version = 'cx_generation_execution_record.v1'),
    tenant_ref_type TEXT NOT NULL CHECK (tenant_ref_type = 'oa.tenant'),
    tenant_ref_id TEXT NOT NULL CHECK (
        tenant_ref_id <> '' AND char_length(tenant_ref_id) <= 128
    ),
    owner_subject_ref_type TEXT NOT NULL CHECK (owner_subject_ref_type = 'oa.user'),
    owner_subject_ref_id TEXT NOT NULL CHECK (
        owner_subject_ref_id <> '' AND char_length(owner_subject_ref_id) <= 128
    ),
    status TEXT NOT NULL CHECK (status IN ('COMPLETED', 'FAILED')),
    retrieval_package_id UUID REFERENCES cx_retrieval_packages(retrieval_package_id),
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    provider_capability TEXT NOT NULL,
    mo_generation_id TEXT,
    request_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(request_metadata) = 'object'),
    response_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(response_metadata) = 'object'),
    mo_runtime_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(mo_runtime_metadata) = 'object'),
    usage JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(usage) = 'object'),
    failure JSONB,
    recovery_lineage JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_cx_gen_exec_private_keys CHECK (
        NOT request_metadata ?| ARRAY[
            'prompt', 'messages', 'content', 'text', 'raw_' || 'prompt', 'api_key'
        ]
        AND NOT response_metadata ?| ARRAY[
            'output_preview', 'raw_output', 'content', 'text'
        ]
        AND NOT mo_runtime_metadata ?| ARRAY[
            'provider_url', 'provider_endpoint', 'model_path', 'api_key'
        ]
    ),
    CONSTRAINT ck_cx_gen_exec_optional_json CHECK (
        (failure IS NULL OR jsonb_typeof(failure) = 'object')
        AND (
            recovery_lineage IS NULL
            OR jsonb_typeof(recovery_lineage) = 'object'
        )
    ),
    CONSTRAINT ck_cx_gen_exec_status_payload CHECK (
        (status = 'COMPLETED' AND failure IS NULL)
        OR (status = 'FAILED' AND failure IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_svc_jobs_owner_created
    ON service_jobs (tenant_ref_id, owner_subject_ref_id, created_at DESC)
    WHERE owner_subject_ref_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cx_proc_owner_updated
    ON cx_document_processing_runs (
        tenant_ref_id,
        owner_subject_ref_id,
        updated_at DESC
    )
    WHERE owner_subject_ref_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cx_ret_owner_created
    ON cx_retrieval_packages (
        tenant_ref_id,
        owner_subject_ref_id,
        created_at DESC
    )
    WHERE owner_subject_ref_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cx_rem_owner_updated
    ON cx_remediation_execution_attempts (
        tenant_ref_id,
        owner_subject_ref_id,
        updated_at DESC
    )
    WHERE owner_subject_ref_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cx_gen_owner_created
    ON cx_generation_executions (
        tenant_ref_id,
        owner_subject_ref_id,
        created_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_cx_gen_retrieval
    ON cx_generation_executions (retrieval_package_id)
    WHERE retrieval_package_id IS NOT NULL;

INSERT INTO schema_migrations (version, description)
VALUES (
    '0917_cx_owner_lineage_persistence',
    'CX owner-scoped job, processing, retrieval, generation, and remediation lineage'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
