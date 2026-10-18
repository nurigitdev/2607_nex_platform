BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE ae_agent_execution
    ADD COLUMN IF NOT EXISTS work_item_ref TEXT NULL,
    ADD COLUMN IF NOT EXISTS claim_ref TEXT NULL,
    ADD COLUMN IF NOT EXISTS claim_generation INTEGER NULL,
    ADD COLUMN IF NOT EXISTS assignment_ref TEXT NULL,
    ADD COLUMN IF NOT EXISTS requester_ref TEXT NULL;

ALTER TABLE ae_agent_execution
    DROP CONSTRAINT IF EXISTS ae_agent_execution_agent_type_check,
    DROP CONSTRAINT IF EXISTS ae_agent_execution_source_type_check,
    DROP CONSTRAINT IF EXISTS ck_ae_execution_agent_type,
    DROP CONSTRAINT IF EXISTS ck_ae_execution_source_type,
    DROP CONSTRAINT IF EXISTS ck_ae_execution_trigger_shape;

ALTER TABLE ae_agent_execution
    ADD CONSTRAINT ck_ae_execution_agent_type
        CHECK (agent_type IN ('IA', 'CA', 'PA', 'EA')),
    ADD CONSTRAINT ck_ae_execution_source_type
        CHECK (source_type IN ('PROMPT', 'CLAIMED_WORKITEM')),
    ADD CONSTRAINT ck_ae_execution_trigger_shape CHECK (
        (
            source_type = 'PROMPT'
            AND agent_type = 'IA'
            AND work_item_ref IS NULL
            AND claim_ref IS NULL
            AND claim_generation IS NULL
            AND assignment_ref IS NULL
        )
        OR
        (
            source_type = 'CLAIMED_WORKITEM'
            AND agent_type IN ('CA', 'PA', 'EA')
            AND project_id IS NOT NULL
            AND char_length(project_id) > 0
            AND work_item_ref IS NOT NULL
            AND char_length(work_item_ref) > 0
            AND claim_ref IS NOT NULL
            AND char_length(claim_ref) > 0
            AND claim_generation >= 1
            AND assignment_ref IS NOT NULL
            AND char_length(assignment_ref) > 0
            AND requester_ref IS NOT NULL
            AND char_length(requester_ref) > 0
        )
    );

CREATE TABLE IF NOT EXISTS ae_claim_handoff_inbox (
    tenant_id TEXT NOT NULL,
    event_id UUID NOT NULL,
    handoff_id UUID NOT NULL,
    handoff_semantic_hash TEXT NOT NULL
        CHECK (handoff_semantic_hash ~ '^sha256:[0-9a-f]{64}$'),
    agent_execution_id UUID NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, event_id),
    CONSTRAINT ux_ae_claim_handoff UNIQUE (tenant_id, handoff_id),
    CONSTRAINT fk_ae_claim_handoff_execution
        FOREIGN KEY (tenant_id, agent_execution_id)
        REFERENCES ae_agent_execution (tenant_id, agent_execution_id)
);

CREATE INDEX IF NOT EXISTS ix_ae_claim_handoff_received
    ON ae_claim_handoff_inbox (received_at DESC, event_id);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2401_ae_claimed_work_execution',
    'AE claimed WorkItem execution admission and handoff inbox'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
