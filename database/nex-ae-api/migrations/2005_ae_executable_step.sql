BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_executable_step (
    tenant_id TEXT NOT NULL,
    executable_step_id TEXT NOT NULL,
    agent_execution_id TEXT NOT NULL,
    step_kind TEXT NOT NULL CHECK (step_kind = 'P4_CHAT_RAG_COMPATIBILITY'),
    state TEXT NOT NULL CHECK (state IN (
        'PENDING', 'READY', 'CLAIMED', 'RUNNING', 'WAITING',
        'RECONCILIATION_REQUIRED', 'SUCCEEDED', 'FAILED', 'BLOCKED',
        'CANCELLED'
    )),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    legacy_interaction_id TEXT NOT NULL,
    retrieval_package_ref TEXT NULL,
    retrieval_package_hash TEXT NULL,
    cx_generation_id TEXT NULL,
    cx_job_id TEXT NULL,
    generated_response_id TEXT NULL,
    result_ref TEXT NULL,
    error_ref TEXT NULL,
    correlation_id TEXT NOT NULL CHECK (char_length(correlation_id) > 0),
    causation_id TEXT NULL,
    invocation_started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, executable_step_id),
    CONSTRAINT ux_ae_step_execution_kind
        UNIQUE (tenant_id, agent_execution_id, step_kind)
);

CREATE INDEX IF NOT EXISTS idx_ae_step_execution_state
    ON ae_executable_step (tenant_id, agent_execution_id, state);

CREATE INDEX IF NOT EXISTS idx_ae_step_interaction
    ON ae_executable_step (tenant_id, legacy_interaction_id);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2005_ae_executable_step',
    'P4 canonical compatibility ExecutableStep and Chat RAG adapter state'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
