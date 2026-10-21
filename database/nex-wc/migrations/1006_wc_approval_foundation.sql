BEGIN;

CREATE TABLE IF NOT EXISTS wc_approval_work_item (
    tenant_id TEXT NOT NULL,
    approval_work_item_id UUID NOT NULL,
    approval_domain TEXT NOT NULL
        CHECK (approval_domain IN ('AGENT_FORMAL', 'NSL_WRITE', 'BUSINESS_FORMAL')),
    source_ref TEXT NOT NULL CHECK (char_length(source_ref) BETWEEN 1 AND 256),
    semantic_hash TEXT NOT NULL CHECK (semantic_hash ~ '^sha256:[0-9a-f]{64}$'),
    title TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 300),
    display_safe_summary TEXT NOT NULL
        CHECK (char_length(display_safe_summary) BETWEEN 1 AND 2000),
    approval_provider_type TEXT NOT NULL
        CHECK (approval_provider_type IN ('AGENT', 'NSL', 'EOS')),
    approval_target_ref TEXT NOT NULL
        CHECK (char_length(approval_target_ref) BETWEEN 1 AND 256),
    target_approver_ref TEXT NULL,
    target_role_ref TEXT NULL,
    target_org_scope_ref TEXT NULL,
    target_project_scope_ref TEXT NULL,
    agent_execution_id TEXT NULL,
    executable_step_id TEXT NULL,
    nsl_execution_id TEXT NULL,
    business_operation_id TEXT NULL,
    approval_request_id TEXT NULL,
    protected_request_ref TEXT NULL,
    resume_target_ref TEXT NOT NULL
        CHECK (char_length(resume_target_ref) BETWEEN 1 AND 256),
    state TEXT NOT NULL CHECK (state IN (
        'PENDING', 'APPROVED', 'REJECTED', 'EXPIRED', 'CANCELLED'
    )),
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    PRIMARY KEY (tenant_id, approval_work_item_id),
    CONSTRAINT ux_wc_aw_source UNIQUE (tenant_id, approval_domain, source_ref),
    CONSTRAINT ck_wc_aw_provider_domain CHECK (
        (approval_domain = 'AGENT_FORMAL' AND approval_provider_type = 'AGENT')
        OR (approval_domain = 'NSL_WRITE' AND approval_provider_type = 'NSL')
        OR (approval_domain = 'BUSINESS_FORMAL' AND approval_provider_type = 'EOS')
    ),
    CONSTRAINT ck_wc_aw_domain_binding CHECK (
        (
            approval_domain = 'NSL_WRITE'
            AND agent_execution_id IS NOT NULL
            AND executable_step_id IS NOT NULL
            AND nsl_execution_id IS NOT NULL
            AND business_operation_id IS NOT NULL
            AND approval_request_id IS NOT NULL
            AND protected_request_ref IS NOT NULL
        )
        OR (
            approval_domain = 'AGENT_FORMAL'
            AND agent_execution_id IS NOT NULL
            AND executable_step_id IS NOT NULL
            AND business_operation_id IS NOT NULL
            AND protected_request_ref IS NOT NULL
        )
        OR (
            approval_domain = 'BUSINESS_FORMAL'
            AND business_operation_id IS NOT NULL
            AND protected_request_ref IS NOT NULL
        )
    ),
    CONSTRAINT ck_wc_aw_expiry CHECK (expires_at IS NULL OR expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS ix_wc_aw_inbox
    ON wc_approval_work_item (
        tenant_id, state, target_approver_ref, target_role_ref, created_at DESC
    );

CREATE INDEX IF NOT EXISTS ix_wc_aw_scope
    ON wc_approval_work_item (
        tenant_id, state, target_org_scope_ref, target_project_scope_ref,
        created_at DESC
    );

CREATE TABLE IF NOT EXISTS wc_approval_decision (
    tenant_id TEXT NOT NULL,
    decision_id UUID NOT NULL,
    approval_work_item_id UUID NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('APPROVE', 'REJECT')),
    decided_by TEXT NOT NULL,
    decision_comment TEXT NULL CHECK (
        decision_comment IS NULL OR char_length(decision_comment) <= 2000
    ),
    decision_version INTEGER NOT NULL CHECK (decision_version >= 1),
    authorized_by_oa BOOLEAN NOT NULL CHECK (authorized_by_oa),
    oa_decision_ref TEXT NOT NULL,
    authorization_revision_hash TEXT NOT NULL
        CHECK (authorization_revision_hash ~ '^sha256:[0-9a-f]{64}$'),
    authorization_checked_at TIMESTAMPTZ NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, decision_id),
    CONSTRAINT fk_wc_ad_work FOREIGN KEY (tenant_id, approval_work_item_id)
        REFERENCES wc_approval_work_item (tenant_id, approval_work_item_id),
    CONSTRAINT ux_wc_ad_version UNIQUE (
        tenant_id, approval_work_item_id, decision_version
    )
);

CREATE INDEX IF NOT EXISTS ix_wc_ad_work_time
    ON wc_approval_decision (tenant_id, approval_work_item_id, decided_at DESC);

CREATE TABLE IF NOT EXISTS wc_approval_outbox (
    tenant_id TEXT NOT NULL,
    outbox_id UUID NOT NULL,
    event_id UUID NOT NULL,
    approval_work_item_id UUID NOT NULL,
    decision_id UUID NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'NSL_APPROVAL_DECIDED',
        'BUSINESS_FORMAL_APPROVAL_DECIDED',
        'AGENT_FORMAL_APPROVAL_DECIDED'
    )),
    event_payload JSONB NOT NULL,
    delivery_state TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (delivery_state IN ('PENDING', 'ENQUEUED', 'DELIVERED', 'FAILED')),
    enqueued_job_id TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, outbox_id),
    CONSTRAINT fk_wc_ao_work FOREIGN KEY (tenant_id, approval_work_item_id)
        REFERENCES wc_approval_work_item (tenant_id, approval_work_item_id),
    CONSTRAINT fk_wc_ao_decision FOREIGN KEY (tenant_id, decision_id)
        REFERENCES wc_approval_decision (tenant_id, decision_id),
    CONSTRAINT ux_wc_ao_event UNIQUE (tenant_id, event_id)
);

CREATE INDEX IF NOT EXISTS ix_wc_ao_delivery
    ON wc_approval_outbox (delivery_state, created_at, outbox_id);

INSERT INTO schema_migrations (version, description)
VALUES ('1006_wc_approval_foundation', 'WC durable human approval aggregate foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
