BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_agent_context (
    tenant_id TEXT NOT NULL,
    context_id UUID NOT NULL,
    context_generation INTEGER NOT NULL
        CHECK (context_generation BETWEEN 1 AND 9999),
    agent_execution_id UUID NOT NULL,
    work_intent_id UUID NOT NULL,
    work_intent_revision INTEGER NOT NULL CHECK (work_intent_revision >= 1),
    work_intent_hash TEXT NOT NULL
        CHECK (work_intent_hash ~ '^sha256:[0-9a-f]{64}$'),
    principal_id TEXT NOT NULL CHECK (char_length(principal_id) BETWEEN 1 AND 200),
    agent_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    conversation_id UUID NOT NULL,
    interaction_id UUID NOT NULL,
    context_hash TEXT NOT NULL CHECK (context_hash ~ '^sha256:[0-9a-f]{64}$'),
    context_json JSONB NOT NULL,
    built_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, context_id),
    CONSTRAINT ux_ae_agent_context_generation
        UNIQUE (tenant_id, agent_execution_id, context_generation),
    CONSTRAINT fk_ae_agent_context_execution
        FOREIGN KEY (tenant_id, agent_execution_id)
        REFERENCES ae_agent_execution (tenant_id, agent_execution_id),
    CONSTRAINT fk_ae_agent_context_intent
        FOREIGN KEY (tenant_id, work_intent_id)
        REFERENCES ae_work_intent (tenant_id, work_intent_id),
    CONSTRAINT ck_ae_agent_context_json_object
        CHECK (jsonb_typeof(context_json) = 'object'),
    CONSTRAINT ck_ae_agent_context_json_identity CHECK (
        context_json ->> 'schema_version' = '1.1'
        AND context_json ->> 'context_id' = context_id::text
        AND (context_json ->> 'context_generation')::integer = context_generation
        AND context_json ->> 'execution_id' = agent_execution_id::text
        AND context_json ->> 'context_hash' = context_hash
    )
);

CREATE INDEX IF NOT EXISTS idx_ae_agent_context_execution
    ON ae_agent_context (tenant_id, agent_execution_id, context_generation DESC);

CREATE INDEX IF NOT EXISTS idx_ae_agent_context_intent
    ON ae_agent_context (tenant_id, work_intent_id, work_intent_revision);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2102_ae_agent_context',
    'Immutable generation-based P5 AgentContext persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
