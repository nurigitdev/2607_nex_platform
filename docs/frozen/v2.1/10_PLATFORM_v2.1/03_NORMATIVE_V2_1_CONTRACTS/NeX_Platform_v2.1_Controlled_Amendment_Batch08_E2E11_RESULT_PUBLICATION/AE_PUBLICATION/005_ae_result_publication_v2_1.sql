-- NeX-AE AgentResult / ResultDelivery / Publication Reconciliation v2.1
CREATE TABLE IF NOT EXISTS ae_agent_result (
    tenant_id              text        NOT NULL,
    result_id              text        NOT NULL,
    agent_execution_id     text        NOT NULL,
    agent_type             text        NOT NULL,
    status                 text        NOT NULL,
    quality                text        NULL,
    structured_result_json jsonb       NOT NULL DEFAULT '{}'::jsonb,
    result_hash            text        NOT NULL,
    source_work_item_ref    text        NULL,
    source_claim_ref        text        NULL,
    source_claim_generation integer     NULL,
    source_claimant_agent_id text       NULL,
    source_assignment_ref   text        NULL,
    created_at             timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, result_id),
    UNIQUE (tenant_id, agent_execution_id, result_id),
    CHECK (agent_type NOT IN ('CA','PA','EA') OR
           (source_work_item_ref IS NOT NULL AND source_claim_ref IS NOT NULL AND source_claim_generation >= 1 AND
            source_claimant_agent_id IS NOT NULL AND source_assignment_ref IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS ae_result_delivery (
    tenant_id                      text        NOT NULL,
    delivery_id                    text        NOT NULL,
    result_id                      text        NOT NULL,
    agent_execution_id             text        NOT NULL,
    target_type                    text        NOT NULL,
    target_ref                     text        NOT NULL,
    required                       boolean     NOT NULL,
    state                          text        NOT NULL,
    publication_operation_id       text        NOT NULL,
    idempotency_key_ref            text        NOT NULL,
    attempt_no                     integer     NOT NULL DEFAULT 0,
    external_delivery_ref          text        NULL,
    latest_preflight_ref           text        NULL,
    publication_reconciliation_ref text        NULL,
    correlation_id                 text        NOT NULL,
    causation_id                   text        NULL,
    created_at                     timestamptz NOT NULL DEFAULT now(),
    updated_at                     timestamptz NOT NULL DEFAULT now(),
    acknowledged_at                timestamptz NULL,
    PRIMARY KEY (tenant_id, delivery_id),
    UNIQUE (tenant_id, result_id, target_type, target_ref),
    UNIQUE (tenant_id, publication_operation_id),
    UNIQUE (tenant_id, idempotency_key_ref),
    CHECK (state IN ('PENDING','SENDING','ACKNOWLEDGED','RETRY_PENDING','UNKNOWN_DELIVERY','FAILED','CANCELLED')),
    CHECK (target_type NOT IN ('NOTIFICATION','EMAIL','MESSENGER','WA_PROJECTION','METRICS','ANALYTICS','DASHBOARD_CACHE') OR required = false),
    CHECK (target_type <> 'WC_WORK_RESULT' OR required = true),
    CHECK (state <> 'ACKNOWLEDGED' OR acknowledged_at IS NOT NULL),
    CHECK (state NOT IN ('SENDING','RETRY_PENDING','UNKNOWN_DELIVERY','ACKNOWLEDGED') OR latest_preflight_ref IS NOT NULL),
    CHECK (state <> 'UNKNOWN_DELIVERY' OR publication_reconciliation_ref IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS ae_result_publication_preflight (
    tenant_id                    text        NOT NULL,
    preflight_id                  text        NOT NULL,
    agent_execution_id            text        NOT NULL,
    result_id                     text        NOT NULL,
    delivery_id                   text        NOT NULL,
    target_type                   text        NOT NULL,
    target_ref                    text        NOT NULL,
    oa_decision_ref               text        NOT NULL,
    authorization_time_semantics  text        NOT NULL DEFAULT 'AS_OF_NOW',
    project_scope_checked         boolean     NOT NULL,
    org_scope_checked             boolean     NOT NULL,
    data_classification_checked   boolean     NOT NULL,
    recipient_visibility_checked  boolean     NOT NULL,
    resource_visibility_checked   boolean     NOT NULL,
    work_claim_lineage_ref         text        NULL,
    claim_status_checked           boolean     NULL,
    claim_generation_current       boolean     NULL,
    claimant_matches               boolean     NULL,
    assignment_matches             boolean     NULL,
    execution_matches              boolean     NULL,
    decision                      text        NOT NULL,
    reason_codes_json             jsonb       NOT NULL DEFAULT '[]'::jsonb,
    correlation_id                text        NOT NULL,
    evaluated_at                  timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, preflight_id),
    CHECK (authorization_time_semantics = 'AS_OF_NOW'),
    CHECK (decision IN ('ALLOW','DENY')),
    CHECK (decision <> 'ALLOW' OR (project_scope_checked AND org_scope_checked AND data_classification_checked AND recipient_visibility_checked AND resource_visibility_checked)),
    CHECK (target_type <> 'WC_WORK_RESULT' OR work_claim_lineage_ref IS NOT NULL),
    CHECK (NOT (target_type='WC_WORK_RESULT' AND decision='ALLOW') OR
           (claim_status_checked IS TRUE AND claim_generation_current IS TRUE AND claimant_matches IS TRUE AND assignment_matches IS TRUE AND execution_matches IS TRUE))
);

CREATE TABLE IF NOT EXISTS ae_result_delivery_attempt (
    attempt_id               text        PRIMARY KEY,
    tenant_id                text        NOT NULL,
    delivery_id              text        NOT NULL,
    attempt_no               integer     NOT NULL,
    preflight_ref            text        NOT NULL,
    request_ref              text        NULL,
    outcome                  text        NOT NULL,
    external_delivery_ref    text        NULL,
    error_ref                text        NULL,
    started_at               timestamptz NOT NULL,
    ended_at                 timestamptz NULL,
    UNIQUE (tenant_id, delivery_id, attempt_no)
);

CREATE TABLE IF NOT EXISTS ae_publication_reconciliation_case (
    publication_reconciliation_id text        PRIMARY KEY,
    tenant_id                     text        NOT NULL,
    agent_execution_id            text        NOT NULL,
    result_id                     text        NOT NULL,
    result_delivery_id            text        NOT NULL,
    publication_operation_id      text        NOT NULL,
    idempotency_key_ref           text        NOT NULL,
    target_type                   text        NOT NULL,
    target_ref                    text        NOT NULL,
    reason                        text        NOT NULL DEFAULT 'UNKNOWN_DELIVERY',
    state                         text        NOT NULL,
    attempt_no                    integer     NOT NULL DEFAULT 0,
    next_check_at                 timestamptz NULL,
    deadline_at                   timestamptz NULL,
    latest_outcome_ref            text        NULL,
    correlation_id                text        NOT NULL,
    causation_id                  text        NULL,
    created_at                    timestamptz NOT NULL DEFAULT now(),
    updated_at                    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, result_delivery_id, publication_operation_id),
    CHECK (reason = 'UNKNOWN_DELIVERY')
);

-- Exactly one canonical WC WorkResult delivery per AgentResult.
CREATE UNIQUE INDEX IF NOT EXISTS uq_ae_result_delivery_wc_work_result
ON ae_result_delivery(tenant_id, result_id) WHERE target_type='WC_WORK_RESULT';
