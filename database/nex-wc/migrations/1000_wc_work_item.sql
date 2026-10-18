BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wc_work_item (
    tenant_id TEXT NOT NULL,
    work_item_id UUID NOT NULL,
    idempotency_key TEXT NOT NULL CHECK (idempotency_key ~ '^sha256:[0-9a-f]{64}$'),
    delegation_semantic_hash TEXT NOT NULL
        CHECK (delegation_semantic_hash ~ '^sha256:[0-9a-f]{64}$'),
    delegation_spec JSONB NOT NULL,
    work_item JSONB NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'CREATED', 'ROUTED', 'ASSIGNED', 'IN_PROGRESS', 'BLOCKED',
        'WAITING_INPUT', 'RESULT_SUBMITTED', 'REVISION_REQUESTED',
        'CLOSED', 'CANCELLED'
    )),
    source_type TEXT NOT NULL CHECK (source_type = 'AGENT_PLAN_STEP'),
    parent_execution_id TEXT NOT NULL,
    parent_plan_id TEXT NOT NULL,
    parent_step_id TEXT NOT NULL,
    delegation_revision INTEGER NOT NULL CHECK (delegation_revision >= 1),
    project_id TEXT NOT NULL,
    required_agent_type TEXT NOT NULL CHECK (required_agent_type IN ('CA', 'PA', 'EA')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, work_item_id),
    CONSTRAINT ux_wc_work_item_semantic_key UNIQUE (tenant_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_wc_work_item_state_created
    ON wc_work_item (tenant_id, state, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_wc_work_item_project_state
    ON wc_work_item (tenant_id, project_id, state, created_at DESC);

CREATE TABLE IF NOT EXISTS wc_routing_decision (
    tenant_id TEXT NOT NULL,
    routing_decision_id UUID NOT NULL,
    work_item_id UUID NOT NULL,
    decision_version INTEGER NOT NULL CHECK (decision_version >= 1),
    policy_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('SELECTED', 'NO_ELIGIBLE_AGENT', 'DENIED')),
    selected_agent_id UUID NULL,
    decision JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, routing_decision_id),
    CONSTRAINT fk_wc_route_work_item FOREIGN KEY (tenant_id, work_item_id)
        REFERENCES wc_work_item (tenant_id, work_item_id),
    CONSTRAINT ux_wc_route_version UNIQUE (tenant_id, work_item_id, decision_version)
);

CREATE TABLE IF NOT EXISTS wc_event_outbox (
    tenant_id TEXT NOT NULL,
    outbox_id UUID NOT NULL,
    event_id UUID NOT NULL,
    work_item_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    event_payload JSONB NOT NULL,
    delivery_state TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (delivery_state IN ('PENDING', 'ENQUEUED', 'DELIVERED', 'FAILED')),
    enqueued_job_id TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, outbox_id),
    CONSTRAINT fk_wc_outbox_work_item FOREIGN KEY (tenant_id, work_item_id)
        REFERENCES wc_work_item (tenant_id, work_item_id),
    CONSTRAINT ux_wc_outbox_event UNIQUE (tenant_id, event_id)
);

CREATE INDEX IF NOT EXISTS ix_wc_outbox_delivery_created
    ON wc_event_outbox (delivery_state, created_at, outbox_id);

INSERT INTO schema_migrations (version, description)
VALUES ('1000_wc_work_item', 'WC durable WorkItem, route, and event outbox foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
