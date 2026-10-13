BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_work_intent (
    tenant_id TEXT NOT NULL,
    work_intent_id UUID NOT NULL,
    intent_revision INTEGER NOT NULL CHECK (intent_revision BETWEEN 1 AND 99),
    agent_execution_id UUID NOT NULL,
    supersedes_work_intent_id UUID NULL,
    source_ref TEXT NOT NULL CHECK (char_length(source_ref) BETWEEN 1 AND 200),
    actor_ref TEXT NOT NULL CHECK (char_length(actor_ref) BETWEEN 1 AND 200),
    compatibility_execution_mode TEXT NOT NULL CHECK (
        compatibility_execution_mode IN (
            'GENERAL_ANSWER', 'GROUNDED_ANSWER',
            'DOCUMENT_SUMMARY', 'DOCUMENT_GENERATION'
        )
    ),
    work_class TEXT NOT NULL CHECK (
        work_class IN ('QUERY', 'ANALYSIS', 'DOCUMENT', 'REPORTING')
    ),
    intent_hash TEXT NOT NULL CHECK (intent_hash ~ '^sha256:[0-9a-f]{64}$'),
    intent_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, work_intent_id),
    CONSTRAINT ux_ae_work_intent_execution_revision
        UNIQUE (tenant_id, agent_execution_id, intent_revision),
    CONSTRAINT fk_ae_work_intent_execution
        FOREIGN KEY (tenant_id, agent_execution_id)
        REFERENCES ae_agent_execution (tenant_id, agent_execution_id),
    CONSTRAINT fk_ae_work_intent_supersedes
        FOREIGN KEY (tenant_id, supersedes_work_intent_id)
        REFERENCES ae_work_intent (tenant_id, work_intent_id),
    CONSTRAINT ck_ae_work_intent_revision_chain CHECK (
        (intent_revision = 1 AND supersedes_work_intent_id IS NULL)
        OR (intent_revision > 1 AND supersedes_work_intent_id IS NOT NULL)
    ),
    CONSTRAINT ck_ae_work_intent_json_object
        CHECK (jsonb_typeof(intent_json) = 'object'),
    CONSTRAINT ck_ae_work_intent_json_identity CHECK (
        intent_json ->> 'schema_version' = '1.1'
        AND intent_json ->> 'work_intent_id' = work_intent_id::text
        AND intent_json ->> 'execution_id' = agent_execution_id::text
        AND (intent_json ->> 'intent_revision')::integer = intent_revision
        AND intent_json ->> 'intent_hash' = intent_hash
    )
);

CREATE INDEX IF NOT EXISTS idx_ae_work_intent_execution
    ON ae_work_intent (tenant_id, agent_execution_id, intent_revision DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2101_ae_work_intent',
    'Immutable revisioned P5 WorkIntent persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
