BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_nsl_step_execution (
    tenant_id TEXT NOT NULL CHECK (char_length(tenant_id) BETWEEN 1 AND 128),
    executable_step_id TEXT NOT NULL,
    agent_execution_id UUID NOT NULL,
    executable_plan_id UUID NOT NULL,
    agent_context_id UUID NOT NULL,
    nsl_execution_id UUID NOT NULL,
    business_operation_id UUID NOT NULL,
    verified_artifact_ref TEXT NOT NULL
        CHECK (char_length(verified_artifact_ref) BETWEEN 1 AND 512),
    verified_artifact_hash TEXT NOT NULL
        CHECK (verified_artifact_hash ~ '^sha256:[0-9a-f]{64}$'),
    request_ref TEXT NOT NULL CHECK (char_length(request_ref) BETWEEN 1 AND 512),
    request_hash TEXT NOT NULL CHECK (request_hash ~ '^sha256:[0-9a-f]{64}$'),
    backend_profile TEXT NOT NULL CHECK (backend_profile = 'NSL_V01_PROCESS_ISOLATED'),
    state TEXT NOT NULL CHECK (state IN (
        'ALLOCATED', 'REQUEST_BOUND', 'RUNNING', 'SUCCEEDED',
        'FAILED', 'BLOCKED', 'CANCELLED'
    )),
    binding_json JSONB NOT NULL CHECK (jsonb_typeof(binding_json) = 'object'),
    request_json JSONB NOT NULL CHECK (jsonb_typeof(request_json) = 'object'),
    context_projection_json JSONB NOT NULL
        CHECK (jsonb_typeof(context_projection_json) = 'object'),
    allocated_at TIMESTAMPTZ NOT NULL,
    request_bound_at TIMESTAMPTZ NULL,
    invocation_started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, executable_step_id),
    CONSTRAINT ux_ae_nsl_step_nsl_id UNIQUE (tenant_id, nsl_execution_id),
    CONSTRAINT ux_ae_nsl_step_boi UNIQUE (tenant_id, business_operation_id),
    CONSTRAINT ux_ae_nsl_step_request UNIQUE (tenant_id, request_ref),
    CONSTRAINT fk_ae_nsl_step_step
        FOREIGN KEY (tenant_id, executable_step_id)
        REFERENCES ae_executable_step (tenant_id, executable_step_id),
    CONSTRAINT fk_ae_nsl_step_execution
        FOREIGN KEY (tenant_id, agent_execution_id)
        REFERENCES ae_agent_execution (tenant_id, agent_execution_id),
    CONSTRAINT fk_ae_nsl_step_plan
        FOREIGN KEY (tenant_id, executable_plan_id)
        REFERENCES ae_executable_plan (tenant_id, executable_plan_id),
    CONSTRAINT fk_ae_nsl_step_context
        FOREIGN KEY (tenant_id, agent_context_id)
        REFERENCES ae_agent_context (tenant_id, context_id),
    CONSTRAINT fk_ae_nsl_step_artifact
        FOREIGN KEY (tenant_id, verified_artifact_ref)
        REFERENCES ae_nsl_artifact (tenant_id, artifact_ref),
    CONSTRAINT ck_ae_nsl_step_json CHECK (
        binding_json ->> 'schema_version' = '1.0'
        AND binding_json ->> 'tenant_id' = tenant_id
        AND binding_json ->> 'executable_step_id' = executable_step_id
        AND binding_json ->> 'nsl_execution_id' = nsl_execution_id::text
        AND binding_json ->> 'business_operation_id' = business_operation_id::text
        AND binding_json ->> 'verified_artifact_ref' = verified_artifact_ref
        AND binding_json ->> 'verified_artifact_hash' = verified_artifact_hash
        AND binding_json ->> 'request_ref' = request_ref
        AND binding_json ->> 'request_hash' = request_hash
        AND binding_json ->> 'backend_profile' = backend_profile
        AND binding_json ->> 'state' = state
        AND request_json ->> 'schema_version' = '1.0'
        AND request_json ->> 'tenant_id' = tenant_id
        AND request_json ->> 'executable_step_id' = executable_step_id
        AND request_json ->> 'nsl_execution_id' = nsl_execution_id::text
        AND request_json ->> 'business_operation_id' = business_operation_id::text
        AND context_projection_json ->> 'schema_version' = '1.0'
        AND request_json ->> 'context_projection_hash'
            = context_projection_json ->> 'projection_hash'
    )
);

CREATE INDEX IF NOT EXISTS idx_ae_nsl_step_state
    ON ae_nsl_step_execution (tenant_id, state, updated_at);

ALTER TABLE ae_step_result
    DROP CONSTRAINT IF EXISTS ae_step_result_business_operation_id_check,
    DROP CONSTRAINT IF EXISTS ae_step_result_operation_fingerprint_check,
    DROP CONSTRAINT IF EXISTS ck_ae_step_result_json_identity;

ALTER TABLE ae_step_result
    ADD COLUMN IF NOT EXISTS executor_kind TEXT NULL;

ALTER TABLE ae_step_result
    ADD CONSTRAINT ck_ae_step_result_v12 CHECK (
        operation_fingerprint IS NULL
        AND (
            (
                result_json ->> 'schema_version' = '1.1'
                AND executor_kind IS NULL
                AND business_operation_id IS NULL
                AND result_json -> 'business_operation_id' = 'null'::jsonb
            )
            OR
            (
                result_json ->> 'schema_version' = '1.2'
                AND executor_kind = result_json ->> 'executor_kind'
                AND (
                    (executor_kind = 'LOCAL_SKILL' AND business_operation_id IS NOT NULL)
                    OR
                    (executor_kind <> 'LOCAL_SKILL' AND business_operation_id IS NULL)
                )
            )
        )
    ),
    ADD CONSTRAINT ck_ae_step_result_json_v12 CHECK (
        result_json ->> 'step_result_id' = step_result_id::text
        AND result_json ->> 'execution_id' = agent_execution_id::text
        AND result_json ->> 'executable_plan_id' = executable_plan_id::text
        AND result_json ->> 'executable_step_id' = executable_step_id
        AND result_json ->> 'result_hash' = result_hash
        AND result_json -> 'operation_fingerprint' = 'null'::jsonb
    );

CREATE INDEX IF NOT EXISTS idx_ae_step_result_boi
    ON ae_step_result (tenant_id, business_operation_id)
    WHERE business_operation_id IS NOT NULL;

INSERT INTO schema_migrations (version, description)
VALUES (
    '2202_ae_nsl_step_execution',
    'P6 durable NSL step binding, canonical request, and StepResult v1.2 support'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
