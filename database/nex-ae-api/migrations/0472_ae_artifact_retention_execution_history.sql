BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_artifact_retention_executions (
    retention_execution_id TEXT PRIMARY KEY,
    execution_history_schema_version TEXT NOT NULL DEFAULT 'ae_artifact_retention_execution_history.v1'
        CHECK (execution_history_schema_version = 'ae_artifact_retention_execution_history.v1'),
    artifact_retention_execution_schema_version TEXT NOT NULL DEFAULT 'ae_artifact_retention_execution.v1'
        CHECK (artifact_retention_execution_schema_version = 'ae_artifact_retention_execution.v1'),
    policy_id TEXT NOT NULL,
    service_id TEXT NOT NULL DEFAULT 'nex-ae-api'
        CHECK (service_id = 'nex-ae-api'),
    mode TEXT NOT NULL CHECK (mode IN ('DRY_RUN', 'EXECUTE')),
    execution_status TEXT NOT NULL
        CHECK (execution_status IN ('PLANNED', 'SUCCEEDED', 'BLOCKED', 'FAILED')),
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    retention_days_after_logical_purge INTEGER NOT NULL
        CHECK (
            retention_days_after_logical_purge >= 1
            AND retention_days_after_logical_purge <= 365
        ),
    as_of TIMESTAMPTZ NOT NULL,
    cutoff_at TIMESTAMPTZ NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL,
    scan_limit INTEGER NOT NULL CHECK (scan_limit >= 1 AND scan_limit <= 100),
    max_delete_count INTEGER NOT NULL
        CHECK (max_delete_count >= 1 AND max_delete_count <= 100),
    candidate_count INTEGER NOT NULL CHECK (candidate_count >= 0),
    selected_count INTEGER NOT NULL CHECK (selected_count >= 0),
    delete_enabled BOOLEAN NOT NULL DEFAULT false,
    storage_mutation_enabled BOOLEAN NOT NULL DEFAULT false,
    database_row_delete_enabled BOOLEAN NOT NULL DEFAULT false,
    deleted_counts JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(deleted_counts) = 'object'),
    requested_by JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(requested_by) = 'object'),
    idempotency_key TEXT,
    trace_id TEXT CHECK (
        trace_id IS NULL
        OR trace_id ~ '^[0-9a-f]{32}$'
    ),
    request_id TEXT,
    blocked_reason TEXT,
    error JSONB CHECK (
        error IS NULL
        OR jsonb_typeof(error) = 'object'
    ),
    audit JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(audit) = 'object'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    execution JSONB NOT NULL
        CHECK (jsonb_typeof(execution) = 'object'),
    execution_payload_hash TEXT NOT NULL
        CHECK (execution_payload_hash ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_ae_artifact_retention_executions_count_order
        CHECK (
            selected_count <= candidate_count
            AND selected_count <= max_delete_count
        ),
    CONSTRAINT ck_ae_artifact_retention_executions_dry_run_flags
        CHECK (
            mode <> 'DRY_RUN'
            OR (
                delete_enabled = false
                AND storage_mutation_enabled = false
                AND database_row_delete_enabled = false
            )
        ),
    CONSTRAINT ck_ae_artifact_retention_executions_execute_flags
        CHECK (
            mode <> 'EXECUTE'
            OR execution_status <> 'SUCCEEDED'
            OR (
                delete_enabled = true
                AND storage_mutation_enabled = true
                AND database_row_delete_enabled = true
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_retention_executions_scope_checked
    ON ae_artifact_retention_executions
    (tenant_id, workspace_id, owner_user_id, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_retention_executions_status_checked
    ON ae_artifact_retention_executions (execution_status, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_retention_executions_mode_checked
    ON ae_artifact_retention_executions (mode, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_retention_executions_trace
    ON ae_artifact_retention_executions (trace_id);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_retention_executions_request
    ON ae_artifact_retention_executions (request_id);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ae_artifact_retention_executions_idempotency
    ON ae_artifact_retention_executions
    (tenant_id, workspace_id, owner_user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

INSERT INTO schema_migrations (version, description)
VALUES (
    '0472_ae_artifact_retention_execution_history',
    'AE artifact retention execution history persistence foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
