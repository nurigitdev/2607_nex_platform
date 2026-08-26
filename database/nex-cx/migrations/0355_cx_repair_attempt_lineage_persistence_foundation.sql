BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cx_remediation_execution_attempts (
    remediation_action_id TEXT PRIMARY KEY,
    result_schema_version TEXT NOT NULL DEFAULT 'cx_remediation_execution_result.v1'
        CHECK (result_schema_version = 'cx_remediation_execution_result.v1'),
    parent_cx_generation_id TEXT NOT NULL,
    root_cx_generation_id TEXT NOT NULL,
    repair_cx_generation_id TEXT,
    tenant_id TEXT,
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    action_type TEXT NOT NULL CHECK (
        action_type IN ('retry_generation', 'retrieval_repair', 'citation_repair')
    ),
    lineage_type TEXT NOT NULL CHECK (
        lineage_type IN ('retry', 'fresh_retrieval_regenerate', 'repair')
    ),
    execution_status TEXT NOT NULL CHECK (
        execution_status IN ('ACCEPTED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')
    ),
    attempt_no INTEGER NOT NULL DEFAULT 1 CHECK (attempt_no >= 1),
    result_ref JSONB,
    failure JSONB,
    redaction_summary JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(redaction_summary) = 'object'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_cx_remediation_execution_action_lineage CHECK (
        (action_type = 'retry_generation' AND lineage_type = 'retry')
        OR (
            action_type = 'retrieval_repair'
            AND lineage_type = 'fresh_retrieval_regenerate'
        )
        OR (action_type = 'citation_repair' AND lineage_type = 'repair')
    ),
    CONSTRAINT ck_cx_remediation_execution_parent_immutable CHECK (
        repair_cx_generation_id IS NULL
        OR repair_cx_generation_id <> parent_cx_generation_id
    ),
    CONSTRAINT ck_cx_remediation_execution_succeeded_result CHECK (
        execution_status <> 'SUCCEEDED'
        OR (
            repair_cx_generation_id IS NOT NULL
            AND result_ref IS NOT NULL
            AND failure IS NULL
        )
    ),
    CONSTRAINT ck_cx_remediation_execution_failed_result CHECK (
        execution_status <> 'FAILED'
        OR (
            repair_cx_generation_id IS NULL
            AND result_ref IS NULL
            AND failure IS NOT NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_cx_remediation_execution_parent_updated
    ON cx_remediation_execution_attempts (parent_cx_generation_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_cx_remediation_execution_root_updated
    ON cx_remediation_execution_attempts (root_cx_generation_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_cx_remediation_execution_trace
    ON cx_remediation_execution_attempts (trace_id);

CREATE INDEX IF NOT EXISTS idx_cx_remediation_execution_status_updated
    ON cx_remediation_execution_attempts (execution_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_cx_remediation_execution_repair_generation
    ON cx_remediation_execution_attempts (repair_cx_generation_id)
    WHERE repair_cx_generation_id IS NOT NULL;

INSERT INTO schema_migrations (version, description)
VALUES (
    '0355_cx_repair_attempt_lineage_persistence_foundation',
    'CX repair attempt lineage persistence foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
