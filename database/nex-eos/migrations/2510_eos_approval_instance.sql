BEGIN;

CREATE TABLE IF NOT EXISTS eos_approval_instance (
    tenant_id VARCHAR(128) NOT NULL,
    approval_instance_id UUID NOT NULL,
    idempotency_key VARCHAR(256) NOT NULL,
    approval_policy_id UUID NOT NULL,
    policy_version INTEGER NOT NULL,
    policy_hash VARCHAR(71) NOT NULL,
    approval_domain VARCHAR(32) NOT NULL,
    business_operation_id UUID NOT NULL,
    operation VARCHAR(128) NOT NULL,
    protected_operation_ref VARCHAR(256) NOT NULL,
    payload_hash VARCHAR(71) NOT NULL,
    write_intent_hash VARCHAR(71) NOT NULL,
    requester_ref_type VARCHAR(32) NOT NULL,
    requester_id VARCHAR(128) NOT NULL,
    org_unit_id UUID NOT NULL,
    project_id UUID NOT NULL,
    state VARCHAR(16) NOT NULL,
    active_stage_order INTEGER,
    stage_count INTEGER NOT NULL,
    version INTEGER NOT NULL,
    expires_at TIMESTAMPTZ,
    correlation_id VARCHAR(128) NOT NULL,
    causation_id VARCHAR(128) NOT NULL,
    binding_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_approval_instance
        PRIMARY KEY (tenant_id, approval_instance_id),
    CONSTRAINT ux_eos_approval_instance_idem
        UNIQUE (tenant_id, idempotency_key),
    CONSTRAINT ux_eos_approval_instance_binding
        UNIQUE (tenant_id, binding_hash),
    CONSTRAINT fk_eos_approval_instance_policy
        FOREIGN KEY (tenant_id, approval_policy_id)
        REFERENCES eos_approval_policy (tenant_id, approval_policy_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_eos_approval_instance_operation
        FOREIGN KEY (tenant_id, business_operation_id)
        REFERENCES eos_business_operation (tenant_id, business_operation_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_eos_approval_instance_org
        FOREIGN KEY (tenant_id, org_unit_id)
        REFERENCES eos_org_unit (tenant_id, org_unit_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_eos_approval_instance_project
        FOREIGN KEY (tenant_id, project_id)
        REFERENCES eos_project (tenant_id, project_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_approval_instance_policy_version CHECK (
        policy_version > 0
    ),
    CONSTRAINT ck_eos_approval_instance_policy_hash CHECK (
        policy_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_approval_instance_domain CHECK (
        approval_domain = 'BUSINESS_FORMAL'
    ),
    CONSTRAINT ck_eos_approval_instance_payload_hash CHECK (
        payload_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_approval_instance_intent_hash CHECK (
        write_intent_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_approval_instance_requester_type CHECK (
        requester_ref_type = 'oa.user'
    ),
    CONSTRAINT ck_eos_approval_instance_state CHECK (
        state IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED', 'INVALIDATED')
    ),
    CONSTRAINT ck_eos_approval_instance_stage_count CHECK (
        stage_count BETWEEN 1 AND 5
    ),
    CONSTRAINT ck_eos_approval_instance_active_stage CHECK (
        active_stage_order IS NULL
        OR active_stage_order BETWEEN 1 AND stage_count
    ),
    CONSTRAINT ck_eos_approval_instance_version CHECK (version > 0),
    CONSTRAINT ck_eos_approval_instance_binding_hash CHECK (
        binding_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_approval_instance_expiry CHECK (
        expires_at IS NULL OR expires_at > created_at
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_approval_instance_operation
    ON eos_approval_instance (
        tenant_id,
        business_operation_id,
        state
    );

CREATE TABLE IF NOT EXISTS eos_approval_stage (
    tenant_id VARCHAR(128) NOT NULL,
    approval_stage_id UUID NOT NULL,
    approval_instance_id UUID NOT NULL,
    stage_order INTEGER NOT NULL,
    policy_stage_order INTEGER NOT NULL,
    position_type VARCHAR(32) NOT NULL,
    quorum_count INTEGER NOT NULL,
    separation_policy VARCHAR(32) NOT NULL,
    state VARCHAR(16) NOT NULL,
    version INTEGER NOT NULL,
    activated_at TIMESTAMPTZ,
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_approval_stage
        PRIMARY KEY (tenant_id, approval_stage_id),
    CONSTRAINT ux_eos_approval_stage_order
        UNIQUE (tenant_id, approval_instance_id, stage_order),
    CONSTRAINT ux_eos_approval_stage_instance
        UNIQUE (tenant_id, approval_instance_id, approval_stage_id),
    CONSTRAINT fk_eos_approval_stage_instance
        FOREIGN KEY (tenant_id, approval_instance_id)
        REFERENCES eos_approval_instance (tenant_id, approval_instance_id)
        ON DELETE CASCADE,
    CONSTRAINT ck_eos_approval_stage_order CHECK (
        stage_order BETWEEN 1 AND 5
    ),
    CONSTRAINT ck_eos_approval_stage_policy_order CHECK (
        policy_stage_order BETWEEN 1 AND 5
    ),
    CONSTRAINT ck_eos_approval_stage_position CHECK (
        position_type IN (
            'PART_LEAD',
            'TEAM_LEAD',
            'GROUP_LEAD',
            'CEO',
            'CHAIRMAN'
        )
    ),
    CONSTRAINT ck_eos_approval_stage_quorum CHECK (quorum_count > 0),
    CONSTRAINT ck_eos_approval_stage_separation CHECK (
        separation_policy = 'REQUESTER_EXCLUDED'
    ),
    CONSTRAINT ck_eos_approval_stage_state CHECK (
        state IN ('WAITING', 'ACTIVE', 'APPROVED', 'REJECTED', 'CANCELLED')
    ),
    CONSTRAINT ck_eos_approval_stage_version CHECK (version > 0),
    CONSTRAINT ck_eos_approval_stage_activation CHECK (
        state = 'WAITING' OR activated_at IS NOT NULL
    ),
    CONSTRAINT ck_eos_approval_stage_decision CHECK (
        state NOT IN ('APPROVED', 'REJECTED') OR decided_at IS NOT NULL
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_eos_approval_stage_active
    ON eos_approval_stage (tenant_id, approval_instance_id)
    WHERE state = 'ACTIVE';

CREATE TABLE IF NOT EXISTS eos_approval_decision (
    tenant_id VARCHAR(128) NOT NULL,
    approval_decision_id UUID NOT NULL,
    approval_instance_id UUID NOT NULL,
    approval_stage_id UUID NOT NULL,
    wc_approval_work_item_id UUID NOT NULL,
    wc_decision_id UUID NOT NULL,
    decision VARCHAR(16) NOT NULL,
    decision_version INTEGER NOT NULL,
    decided_by_ref_type VARCHAR(32) NOT NULL,
    decided_by_id VARCHAR(128) NOT NULL,
    decision_comment TEXT,
    authorized_by_oa BOOLEAN NOT NULL,
    oa_decision_ref VARCHAR(128) NOT NULL,
    authorization_revision_hash VARCHAR(71) NOT NULL,
    authorization_checked_at TIMESTAMPTZ NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    decision_hash VARCHAR(71) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_approval_decision
        PRIMARY KEY (tenant_id, approval_decision_id),
    CONSTRAINT ux_eos_approval_decision_wc
        UNIQUE (tenant_id, wc_decision_id),
    CONSTRAINT ux_eos_approval_decision_version
        UNIQUE (tenant_id, approval_stage_id, decision_version),
    CONSTRAINT ux_eos_approval_decision_hash
        UNIQUE (tenant_id, decision_hash),
    CONSTRAINT fk_eos_approval_decision_stage
        FOREIGN KEY (
            tenant_id,
            approval_instance_id,
            approval_stage_id
        )
        REFERENCES eos_approval_stage (
            tenant_id,
            approval_instance_id,
            approval_stage_id
        )
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_approval_decision_value CHECK (
        decision IN ('APPROVE', 'REJECT')
    ),
    CONSTRAINT ck_eos_approval_decision_version CHECK (
        decision_version > 0
    ),
    CONSTRAINT ck_eos_approval_decision_actor CHECK (
        decided_by_ref_type = 'oa.user'
    ),
    CONSTRAINT ck_eos_approval_decision_oa CHECK (
        authorized_by_oa = TRUE
    ),
    CONSTRAINT ck_eos_approval_decision_auth_hash CHECK (
        authorization_revision_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_approval_decision_hash CHECK (
        decision_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2510_eos_approval_instance',
    'NeX-EOS immutable approval instance, stage, and decision persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
