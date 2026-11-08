BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE ae_agent_execution
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ NULL;

CREATE TABLE IF NOT EXISTS ae_agent_result (
    tenant_id TEXT NOT NULL,
    result_id UUID NOT NULL,
    agent_execution_id UUID NOT NULL,
    agent_type TEXT NOT NULL CHECK (agent_type IN ('IA', 'CA', 'PA', 'EA')),
    agent_id UUID NULL,
    project_id TEXT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'SUCCEEDED', 'PARTIAL', 'BLOCKED', 'FAILED', 'CANCELLED'
    )),
    quality TEXT NULL,
    structured_result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_envelope_json JSONB NOT NULL,
    result_hash TEXT NOT NULL CHECK (result_hash LIKE 'sha256:%'),
    source_work_item_ref TEXT NULL,
    source_claim_ref TEXT NULL,
    source_claim_generation INTEGER NULL,
    source_claimant_agent_id TEXT NULL,
    source_assignment_ref TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, result_id),
    CONSTRAINT ux_ae_result_execution UNIQUE (tenant_id, agent_execution_id),
    CONSTRAINT fk_ae_result_execution
        FOREIGN KEY (tenant_id, agent_execution_id)
        REFERENCES ae_agent_execution (tenant_id, agent_execution_id),
    CHECK (
        agent_type NOT IN ('CA', 'PA', 'EA') OR (
            source_work_item_ref IS NOT NULL
            AND source_claim_ref IS NOT NULL
            AND source_claim_generation >= 1
            AND source_claimant_agent_id IS NOT NULL
            AND source_assignment_ref IS NOT NULL
        )
    )
);

CREATE TABLE IF NOT EXISTS ae_result_delivery (
    tenant_id TEXT NOT NULL,
    delivery_id UUID NOT NULL,
    result_id UUID NOT NULL,
    agent_execution_id UUID NOT NULL,
    target_type TEXT NOT NULL CHECK (target_type IN (
        'WORKSPACE_RESULT', 'WC_WORK_RESULT', 'ARTIFACT_STORE',
        'NOTIFICATION', 'EMAIL', 'MESSENGER', 'WA_PROJECTION',
        'METRICS', 'ANALYTICS', 'DASHBOARD_CACHE'
    )),
    target_ref TEXT NOT NULL CHECK (char_length(target_ref) > 0),
    required BOOLEAN NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'PENDING', 'SENDING', 'ACKNOWLEDGED', 'RETRY_PENDING',
        'UNKNOWN_DELIVERY', 'FAILED', 'CANCELLED'
    )),
    publication_operation_id TEXT NOT NULL,
    idempotency_key_ref TEXT NOT NULL,
    attempt_no INTEGER NOT NULL DEFAULT 0 CHECK (attempt_no >= 0),
    external_delivery_ref TEXT NULL,
    latest_preflight_ref TEXT NULL,
    publication_reconciliation_ref TEXT NULL,
    correlation_id TEXT NOT NULL CHECK (char_length(correlation_id) > 0),
    causation_id TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    acknowledged_at TIMESTAMPTZ NULL,
    PRIMARY KEY (tenant_id, delivery_id),
    CONSTRAINT ux_ae_delivery_target
        UNIQUE (tenant_id, result_id, target_type, target_ref),
    CONSTRAINT ux_ae_delivery_operation
        UNIQUE (tenant_id, publication_operation_id),
    CONSTRAINT ux_ae_delivery_idempotency
        UNIQUE (tenant_id, idempotency_key_ref),
    CONSTRAINT fk_ae_delivery_result
        FOREIGN KEY (tenant_id, result_id)
        REFERENCES ae_agent_result (tenant_id, result_id),
    CHECK (
        target_type NOT IN (
            'NOTIFICATION', 'EMAIL', 'MESSENGER', 'WA_PROJECTION',
            'METRICS', 'ANALYTICS', 'DASHBOARD_CACHE'
        ) OR required = false
    ),
    CHECK (target_type <> 'WC_WORK_RESULT' OR required = true),
    CHECK (state <> 'ACKNOWLEDGED' OR acknowledged_at IS NOT NULL),
    CHECK (
        state NOT IN (
            'SENDING', 'RETRY_PENDING', 'UNKNOWN_DELIVERY', 'ACKNOWLEDGED'
        ) OR latest_preflight_ref IS NOT NULL
    ),
    CHECK (
        state <> 'UNKNOWN_DELIVERY'
        OR publication_reconciliation_ref IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_ae_result_status
    ON ae_agent_result (tenant_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_delivery_state
    ON ae_result_delivery (tenant_id, state, updated_at);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2006_ae_agent_result',
    'Canonical immutable AgentResult and required PENDING workspace delivery'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
