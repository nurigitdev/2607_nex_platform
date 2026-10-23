BEGIN;

CREATE TABLE IF NOT EXISTS eos_approval_policy (
    tenant_id VARCHAR(128) NOT NULL,
    approval_policy_id UUID NOT NULL,
    policy_key VARCHAR(128) NOT NULL,
    version INTEGER NOT NULL,
    name VARCHAR(256) NOT NULL,
    approval_domain VARCHAR(32) NOT NULL,
    risk_level VARCHAR(16),
    minimum_amount NUMERIC(20, 2),
    maximum_amount NUMERIC(20, 2),
    project_id UUID,
    account_id UUID,
    transaction_type VARCHAR(128),
    status VARCHAR(16) NOT NULL,
    effective_from TIMESTAMPTZ NOT NULL,
    effective_until TIMESTAMPTZ,
    policy_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_approval_policy
        PRIMARY KEY (tenant_id, approval_policy_id),
    CONSTRAINT ux_eos_approval_policy_version
        UNIQUE (tenant_id, policy_key, version),
    CONSTRAINT ux_eos_approval_policy_hash
        UNIQUE (tenant_id, policy_hash),
    CONSTRAINT fk_eos_approval_policy_project
        FOREIGN KEY (tenant_id, project_id)
        REFERENCES eos_project (tenant_id, project_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_eos_approval_policy_account
        FOREIGN KEY (tenant_id, account_id)
        REFERENCES eos_account (tenant_id, account_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_approval_policy_version CHECK (version > 0),
    CONSTRAINT ck_eos_approval_policy_domain CHECK (
        approval_domain IN ('AGENT_FORMAL', 'NSL_WRITE', 'BUSINESS_FORMAL')
    ),
    CONSTRAINT ck_eos_approval_policy_risk CHECK (
        risk_level IS NULL
        OR risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
    ),
    CONSTRAINT ck_eos_approval_policy_status CHECK (
        status IN ('ACTIVE', 'INACTIVE')
    ),
    CONSTRAINT ck_eos_approval_policy_period CHECK (
        effective_until IS NULL OR effective_until > effective_from
    ),
    CONSTRAINT ck_eos_approval_policy_minimum CHECK (
        minimum_amount IS NULL OR minimum_amount >= 0
    ),
    CONSTRAINT ck_eos_approval_policy_maximum CHECK (
        maximum_amount IS NULL OR maximum_amount >= 0
    ),
    CONSTRAINT ck_eos_approval_policy_amount_range CHECK (
        minimum_amount IS NULL
        OR maximum_amount IS NULL
        OR maximum_amount > minimum_amount
    ),
    CONSTRAINT ck_eos_approval_policy_transaction CHECK (
        transaction_type IS NULL
        OR transaction_type ~ '^[A-Z][A-Z0-9_.]{0,127}$'
    ),
    CONSTRAINT ck_eos_approval_policy_hash CHECK (
        policy_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_approval_policy_select
    ON eos_approval_policy (
        tenant_id,
        approval_domain,
        status,
        effective_from,
        effective_until
    );

CREATE TABLE IF NOT EXISTS eos_approval_policy_stage (
    tenant_id VARCHAR(128) NOT NULL,
    approval_policy_id UUID NOT NULL,
    stage_order INTEGER NOT NULL,
    position_type VARCHAR(32) NOT NULL,
    quorum_count INTEGER NOT NULL DEFAULT 1,
    separation_policy VARCHAR(32) NOT NULL DEFAULT 'REQUESTER_EXCLUDED',
    CONSTRAINT pk_eos_approval_policy_stage
        PRIMARY KEY (tenant_id, approval_policy_id, stage_order),
    CONSTRAINT fk_eos_approval_policy_stage_policy
        FOREIGN KEY (tenant_id, approval_policy_id)
        REFERENCES eos_approval_policy (tenant_id, approval_policy_id)
        ON DELETE CASCADE,
    CONSTRAINT ux_eos_approval_policy_stage_position
        UNIQUE (tenant_id, approval_policy_id, position_type),
    CONSTRAINT ck_eos_approval_policy_stage_order CHECK (
        stage_order BETWEEN 1 AND 5
    ),
    CONSTRAINT ck_eos_approval_policy_stage_position CHECK (
        position_type IN (
            'PART_LEAD',
            'TEAM_LEAD',
            'GROUP_LEAD',
            'CEO',
            'CHAIRMAN'
        )
    ),
    CONSTRAINT ck_eos_approval_policy_stage_quorum CHECK (quorum_count > 0),
    CONSTRAINT ck_eos_approval_policy_stage_separation CHECK (
        separation_policy = 'REQUESTER_EXCLUDED'
    )
);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2509_eos_approval_policy',
    'NeX-EOS deterministic formal approval policy persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
