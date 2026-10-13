BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_agent_execution (
    tenant_id TEXT NOT NULL,
    agent_execution_id UUID NOT NULL,
    agent_id UUID NOT NULL,
    agent_type TEXT NOT NULL CHECK (agent_type = 'IA'),
    principal_id TEXT NOT NULL,
    trigger_schema_version TEXT NOT NULL DEFAULT '2.1'
        CHECK (trigger_schema_version = '2.1'),
    trigger_id UUID NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type = 'PROMPT'),
    source_ref TEXT NOT NULL CHECK (char_length(source_ref) > 0),
    project_id TEXT NULL,
    workspace_id UUID NULL REFERENCES ae_workspaces(workspace_id),
    conversation_id UUID NULL REFERENCES ae_conversations(conversation_id),
    legacy_interaction_id UUID NULL,
    state TEXT NOT NULL CHECK (state IN (
        'QUEUED', 'RUNNING', 'WAITING_INPUT', 'WAITING_CONFIRMATION',
        'WAITING_APPROVAL', 'WAITING_DEPENDENCY',
        'RECONCILIATION_REQUIRED', 'SUCCEEDED', 'FAILED', 'BLOCKED',
        'ESCALATED', 'CANCELLED'
    )),
    phase TEXT NOT NULL CHECK (phase IN (
        'INTAKE', 'BASE_CONTEXT', 'INTENT_RESOLUTION', 'CONTEXT_EXPANSION',
        'PLAN_BUILD', 'PLAN_VALIDATE', 'PLAN_COMPILE', 'STEP_EXECUTION',
        'RESULT_VERIFY', 'RESULT_SYNTHESIS', 'RESULT_PUBLISH', 'FINALIZE'
    )),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    result_id UUID NULL,
    correlation_id TEXT NOT NULL CHECK (char_length(correlation_id) > 0),
    causation_id TEXT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, agent_execution_id),
    CONSTRAINT fk_ae_execution_agent
        FOREIGN KEY (tenant_id, agent_id)
        REFERENCES ae_agent_identity (tenant_id, agent_id),
    CONSTRAINT ux_ae_execution_trigger UNIQUE (tenant_id, trigger_id)
);

CREATE INDEX IF NOT EXISTS idx_ae_execution_scope_state
    ON ae_agent_execution (tenant_id, principal_id, state, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_execution_conversation
    ON ae_agent_execution (tenant_id, conversation_id, created_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2003_ae_agent_execution',
    'Canonical project-neutral PROMPT trigger and AgentExecution admission'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
