BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ae_nsl_step_run_ref
    ON ae_nsl_step_execution (
        tenant_id, executable_step_id, nsl_execution_id
    );

CREATE TABLE IF NOT EXISTS ae_nsl_backend_run (
    tenant_id VARCHAR(128) NOT NULL,
    nsl_execution_id UUID NOT NULL,
    attempt_no INTEGER NOT NULL,
    executable_step_id TEXT NOT NULL,
    business_operation_id UUID NOT NULL,
    isolation_status VARCHAR(32) NOT NULL,
    runtime_status VARCHAR(32),
    record_hash VARCHAR(71) NOT NULL,
    record_json JSONB NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_ae_nsl_backend_run
        PRIMARY KEY (tenant_id, nsl_execution_id, attempt_no),
    CONSTRAINT fk_ae_nsl_run_binding
        FOREIGN KEY (tenant_id, executable_step_id, nsl_execution_id)
        REFERENCES ae_nsl_step_execution (
            tenant_id, executable_step_id, nsl_execution_id
        ),
    CONSTRAINT ck_ae_nsl_run_attempt
        CHECK (attempt_no BETWEEN 1 AND 10000),
    CONSTRAINT ck_ae_nsl_run_isolation
        CHECK (isolation_status IN (
            'COMPLETED', 'TARGET_ERROR', 'CRASHED', 'TIMED_OUT', 'PROTOCOL_ERROR'
        )),
    CONSTRAINT ck_ae_nsl_run_runtime
        CHECK (runtime_status IS NULL OR runtime_status IN (
            'CREATED', 'RUNNING', 'COMPLETED', 'FAILED', 'TOOL_ERROR',
            'VALIDATION_ERROR', 'LIMIT_EXCEEDED', 'CANCELLED'
        )),
    CONSTRAINT ck_ae_nsl_run_hash
        CHECK (record_hash ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_ae_nsl_run_json
        CHECK (
            record_json ->> 'schema_version' = '1.0'
            AND record_json ->> 'tenant_id' = tenant_id
            AND record_json ->> 'nsl_execution_id' = nsl_execution_id::text
            AND (record_json ->> 'attempt_no')::integer = attempt_no
            AND record_json ->> 'record_hash' = record_hash
        )
);

CREATE INDEX IF NOT EXISTS idx_ae_nsl_run_step
    ON ae_nsl_backend_run (tenant_id, executable_step_id, attempt_no);

CREATE INDEX IF NOT EXISTS idx_ae_nsl_run_state
    ON ae_nsl_backend_run (isolation_status, runtime_status, completed_at);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2204_ae_nsl_backend_run',
    'P6 process-isolated NSL backend run progress and evidence records'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
