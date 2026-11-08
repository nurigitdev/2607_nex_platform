BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_capability_snapshot (
    tenant_id TEXT NOT NULL,
    capability_snapshot_id UUID NOT NULL,
    snapshot_version INTEGER NOT NULL CHECK (snapshot_version BETWEEN 1 AND 9999),
    snapshot_hash TEXT NOT NULL CHECK (snapshot_hash ~ '^sha256:[0-9a-f]{64}$'),
    snapshot_json JSONB NOT NULL CHECK (jsonb_typeof(snapshot_json) = 'object'),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, capability_snapshot_id),
    CONSTRAINT ux_ae_cap_snapshot_version UNIQUE (tenant_id, snapshot_version),
    CONSTRAINT ck_ae_cap_snapshot_json_identity CHECK (
        snapshot_json ->> 'schema_version' = '1.1'
        AND snapshot_json ->> 'capability_snapshot_id' = capability_snapshot_id::text
        AND (snapshot_json ->> 'snapshot_version')::integer = snapshot_version
        AND snapshot_json ->> 'snapshot_hash' = snapshot_hash
    )
);

CREATE TABLE IF NOT EXISTS ae_agent_plan (
    tenant_id TEXT NOT NULL,
    agent_plan_id UUID NOT NULL,
    agent_plan_version INTEGER NOT NULL CHECK (agent_plan_version BETWEEN 1 AND 99),
    agent_execution_id UUID NOT NULL,
    work_intent_id UUID NOT NULL,
    agent_context_id UUID NOT NULL,
    capability_snapshot_id UUID NOT NULL,
    plan_kind TEXT NOT NULL CHECK (plan_kind IN ('DIRECT', 'KNOWN_TEMPLATE')),
    plan_hash TEXT NOT NULL CHECK (plan_hash ~ '^sha256:[0-9a-f]{64}$'),
    plan_json JSONB NOT NULL CHECK (jsonb_typeof(plan_json) = 'object'),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, agent_plan_id),
    CONSTRAINT ux_ae_agent_plan_execution_version
        UNIQUE (tenant_id, agent_execution_id, agent_plan_version),
    CONSTRAINT fk_ae_agent_plan_execution
        FOREIGN KEY (tenant_id, agent_execution_id)
        REFERENCES ae_agent_execution (tenant_id, agent_execution_id),
    CONSTRAINT fk_ae_agent_plan_intent
        FOREIGN KEY (tenant_id, work_intent_id)
        REFERENCES ae_work_intent (tenant_id, work_intent_id),
    CONSTRAINT fk_ae_agent_plan_context
        FOREIGN KEY (tenant_id, agent_context_id)
        REFERENCES ae_agent_context (tenant_id, context_id),
    CONSTRAINT fk_ae_agent_plan_snapshot
        FOREIGN KEY (tenant_id, capability_snapshot_id)
        REFERENCES ae_capability_snapshot (tenant_id, capability_snapshot_id),
    CONSTRAINT ck_ae_agent_plan_json_identity CHECK (
        plan_json ->> 'schema_version' = '1.1'
        AND plan_json ->> 'agent_plan_id' = agent_plan_id::text
        AND (plan_json ->> 'agent_plan_version')::integer = agent_plan_version
        AND plan_json ->> 'execution_id' = agent_execution_id::text
        AND plan_json ->> 'plan_hash' = plan_hash
    )
);

CREATE INDEX IF NOT EXISTS idx_ae_agent_plan_execution
    ON ae_agent_plan (tenant_id, agent_execution_id, agent_plan_version DESC);

CREATE TABLE IF NOT EXISTS ae_plan_validation (
    tenant_id TEXT NOT NULL,
    validation_result_id UUID NOT NULL,
    agent_plan_id UUID NOT NULL,
    agent_plan_version INTEGER NOT NULL CHECK (agent_plan_version BETWEEN 1 AND 99),
    agent_execution_id UUID NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'VALID', 'REPLAN_REQUIRED', 'CONTEXT_REFRESH_REQUIRED',
        'CLARIFICATION_REQUIRED', 'BLOCKED', 'INVALID_TERMINAL',
        'RETRYABLE_VALIDATION_FAILURE'
    )),
    runtime_directive TEXT NOT NULL,
    result_hash TEXT NOT NULL CHECK (result_hash ~ '^sha256:[0-9a-f]{64}$'),
    result_json JSONB NOT NULL CHECK (jsonb_typeof(result_json) = 'object'),
    validated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, validation_result_id),
    CONSTRAINT fk_ae_plan_validation_plan
        FOREIGN KEY (tenant_id, agent_plan_id)
        REFERENCES ae_agent_plan (tenant_id, agent_plan_id),
    CONSTRAINT ck_ae_plan_validation_mapping CHECK (
        (status = 'VALID' AND runtime_directive = 'PROCEED_TO_COMPILE')
        OR (status = 'CLARIFICATION_REQUIRED' AND runtime_directive = 'WAIT_FOR_INPUT')
        OR (status = 'REPLAN_REQUIRED' AND runtime_directive = 'BLOCK_REPLAN_REQUIRED')
        OR (status = 'CONTEXT_REFRESH_REQUIRED'
            AND runtime_directive = 'BLOCK_CONTEXT_REFRESH_REQUIRED')
        OR (status = 'BLOCKED' AND runtime_directive = 'BLOCK_EXECUTION')
        OR (status = 'INVALID_TERMINAL' AND runtime_directive = 'FAIL_VALIDATION')
        OR (status = 'RETRYABLE_VALIDATION_FAILURE'
            AND runtime_directive = 'RETRY_VALIDATION_BOUNDED')
    ),
    CONSTRAINT ck_ae_plan_validation_json_identity CHECK (
        result_json ->> 'schema_version' = '1.1'
        AND result_json ->> 'validation_result_id' = validation_result_id::text
        AND result_json ->> 'execution_id' = agent_execution_id::text
        AND result_json ->> 'result_hash' = result_hash
    )
);

CREATE INDEX IF NOT EXISTS idx_ae_plan_validation_plan_time
    ON ae_plan_validation (tenant_id, agent_plan_id, validated_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2103_ae_capability_plan_validation',
    'P5 capability snapshot, AgentPlan, and validation persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
