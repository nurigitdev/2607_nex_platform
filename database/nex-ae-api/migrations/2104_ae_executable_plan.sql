BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_executable_plan (
    tenant_id TEXT NOT NULL,
    executable_plan_id UUID NOT NULL,
    executable_plan_version INTEGER NOT NULL
        CHECK (executable_plan_version BETWEEN 1 AND 99),
    agent_execution_id UUID NOT NULL,
    agent_plan_id UUID NOT NULL,
    agent_plan_version INTEGER NOT NULL CHECK (agent_plan_version BETWEEN 1 AND 99),
    validation_result_id UUID NOT NULL,
    compiler_version TEXT NOT NULL CHECK (char_length(compiler_version) BETWEEN 1 AND 64),
    plan_hash TEXT NOT NULL CHECK (plan_hash ~ '^sha256:[0-9a-f]{64}$'),
    plan_json JSONB NOT NULL CHECK (jsonb_typeof(plan_json) = 'object'),
    compiled_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, executable_plan_id),
    CONSTRAINT ux_ae_exec_plan_version
        UNIQUE (tenant_id, agent_execution_id, executable_plan_version),
    CONSTRAINT fk_ae_exec_plan_execution
        FOREIGN KEY (tenant_id, agent_execution_id)
        REFERENCES ae_agent_execution (tenant_id, agent_execution_id),
    CONSTRAINT fk_ae_exec_plan_agent_plan
        FOREIGN KEY (tenant_id, agent_plan_id)
        REFERENCES ae_agent_plan (tenant_id, agent_plan_id),
    CONSTRAINT fk_ae_exec_plan_validation
        FOREIGN KEY (tenant_id, validation_result_id)
        REFERENCES ae_plan_validation (tenant_id, validation_result_id),
    CONSTRAINT ck_ae_exec_plan_json_identity CHECK (
        plan_json ->> 'schema_version' = '1.1'
        AND plan_json ->> 'executable_plan_id' = executable_plan_id::text
        AND (plan_json ->> 'executable_plan_version')::integer = executable_plan_version
        AND plan_json ->> 'execution_id' = agent_execution_id::text
        AND plan_json ->> 'executable_plan_hash' = plan_hash
    )
);

CREATE INDEX IF NOT EXISTS idx_ae_exec_plan_execution
    ON ae_executable_plan (tenant_id, agent_execution_id, executable_plan_version DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2104_ae_executable_plan',
    'P5 deterministic ExecutablePlan semantic envelope persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
