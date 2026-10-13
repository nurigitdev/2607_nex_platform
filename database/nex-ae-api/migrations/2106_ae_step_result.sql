BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_step_result (
    tenant_id TEXT NOT NULL,
    step_result_id UUID NOT NULL,
    agent_execution_id UUID NOT NULL,
    executable_plan_id UUID NOT NULL,
    executable_step_id TEXT NOT NULL,
    compiled_step_key TEXT NOT NULL CHECK (compiled_step_key ~ '^E[0-9]{1,3}$'),
    logical_step_id TEXT NOT NULL CHECK (logical_step_id ~ '^S[0-9]{1,3}$'),
    attempt_no INTEGER NOT NULL CHECK (attempt_no >= 1),
    status TEXT NOT NULL CHECK (status IN (
        'SUCCEEDED', 'FAILED', 'BLOCKED', 'CANCELLED'
    )),
    result_contract_ref TEXT NOT NULL
        CHECK (char_length(result_contract_ref) BETWEEN 1 AND 256),
    result_payload JSONB NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
    external_refs JSONB NOT NULL CHECK (jsonb_typeof(external_refs) = 'array'),
    artifact_refs JSONB NOT NULL CHECK (jsonb_typeof(artifact_refs) = 'array'),
    evidence_refs JSONB NOT NULL CHECK (jsonb_typeof(evidence_refs) = 'array'),
    error_ref TEXT NULL CHECK (error_ref IS NULL OR char_length(error_ref) <= 256),
    business_operation_id TEXT NULL CHECK (business_operation_id IS NULL),
    operation_fingerprint TEXT NULL CHECK (operation_fingerprint IS NULL),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    result_hash TEXT NOT NULL CHECK (result_hash ~ '^sha256:[0-9a-f]{64}$'),
    result_json JSONB NOT NULL CHECK (jsonb_typeof(result_json) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, step_result_id),
    CONSTRAINT ux_ae_step_result_step UNIQUE (tenant_id, executable_step_id),
    CONSTRAINT fk_ae_step_result_execution
        FOREIGN KEY (tenant_id, agent_execution_id)
        REFERENCES ae_agent_execution (tenant_id, agent_execution_id),
    CONSTRAINT fk_ae_step_result_plan
        FOREIGN KEY (tenant_id, executable_plan_id)
        REFERENCES ae_executable_plan (tenant_id, executable_plan_id),
    CONSTRAINT fk_ae_step_result_step
        FOREIGN KEY (tenant_id, executable_step_id)
        REFERENCES ae_executable_step (tenant_id, executable_step_id),
    CONSTRAINT ck_ae_step_result_json_identity CHECK (
        result_json ->> 'schema_version' = '1.1'
        AND result_json ->> 'step_result_id' = step_result_id::text
        AND result_json ->> 'execution_id' = agent_execution_id::text
        AND result_json ->> 'executable_plan_id' = executable_plan_id::text
        AND result_json ->> 'executable_step_id' = executable_step_id
        AND result_json ->> 'result_hash' = result_hash
        AND result_json -> 'business_operation_id' = 'null'::jsonb
        AND result_json -> 'operation_fingerprint' = 'null'::jsonb
    )
);

CREATE INDEX IF NOT EXISTS idx_ae_step_result_plan
    ON ae_step_result (tenant_id, executable_plan_id, compiled_step_key);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2106_ae_step_result',
    'P5 immutable terminal StepResult with null WRITE identity'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
