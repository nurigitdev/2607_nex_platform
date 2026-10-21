BEGIN;

CREATE TABLE IF NOT EXISTS eos_business_operation (
    tenant_id VARCHAR(128) NOT NULL,
    business_operation_id UUID NOT NULL,
    idempotency_key VARCHAR(256) NOT NULL,
    operation VARCHAR(128) NOT NULL,
    payload_hash CHAR(71) NOT NULL,
    commit_state VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    result_json JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    committed_at TIMESTAMPTZ,
    CONSTRAINT pk_eos_business_operation
        PRIMARY KEY (tenant_id, business_operation_id),
    CONSTRAINT ux_eos_bo_idempotency
        UNIQUE (tenant_id, idempotency_key),
    CONSTRAINT ck_eos_bo_tenant
        CHECK (tenant_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'),
    CONSTRAINT ck_eos_bo_operation
        CHECK (operation ~ '^[A-Z][A-Z0-9_]{0,127}$'),
    CONSTRAINT ck_eos_bo_payload_hash
        CHECK (payload_hash ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_eos_bo_commit_state
        CHECK (commit_state IN (
            'PENDING',
            'COMMITTED',
            'NOT_COMMITTED',
            'UNKNOWN_COMMIT_STATE'
        )),
    CONSTRAINT ck_eos_bo_result
        CHECK (result_json IS NULL OR jsonb_typeof(result_json) = 'object'),
    CONSTRAINT ck_eos_bo_committed
        CHECK (
            (commit_state = 'PENDING' AND result_json IS NULL AND committed_at IS NULL)
            OR
            (commit_state <> 'PENDING' AND result_json IS NOT NULL AND committed_at IS NOT NULL)
        )
);

CREATE TABLE IF NOT EXISTS eos_idempotency (
    tenant_id VARCHAR(128) NOT NULL,
    idempotency_key VARCHAR(256) NOT NULL,
    business_operation_id UUID NOT NULL,
    operation VARCHAR(128) NOT NULL,
    payload_hash CHAR(71) NOT NULL,
    idempotency_state VARCHAR(16) NOT NULL DEFAULT 'IN_PROGRESS',
    result_json JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    CONSTRAINT pk_eos_idempotency
        PRIMARY KEY (tenant_id, idempotency_key),
    CONSTRAINT ux_eos_idem_operation
        UNIQUE (tenant_id, business_operation_id),
    CONSTRAINT fk_eos_idem_operation
        FOREIGN KEY (tenant_id, business_operation_id)
        REFERENCES eos_business_operation (tenant_id, business_operation_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_idem_operation
        CHECK (operation ~ '^[A-Z][A-Z0-9_]{0,127}$'),
    CONSTRAINT ck_eos_idem_payload_hash
        CHECK (payload_hash ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_eos_idem_state
        CHECK (idempotency_state IN ('IN_PROGRESS', 'COMPLETED')),
    CONSTRAINT ck_eos_idem_result
        CHECK (result_json IS NULL OR jsonb_typeof(result_json) = 'object'),
    CONSTRAINT ck_eos_idem_completed
        CHECK (
            (idempotency_state = 'IN_PROGRESS' AND result_json IS NULL AND completed_at IS NULL)
            OR
            (idempotency_state = 'COMPLETED' AND result_json IS NOT NULL AND completed_at IS NOT NULL)
        )
);

CREATE TABLE IF NOT EXISTS eos_outbox (
    outbox_id UUID PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    event_id UUID NOT NULL,
    business_operation_id UUID NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    event_payload JSONB NOT NULL,
    event_payload_hash CHAR(71) NOT NULL,
    delivery_state VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    CONSTRAINT ux_eos_outbox_event
        UNIQUE (tenant_id, event_id),
    CONSTRAINT ux_eos_outbox_operation_event
        UNIQUE (tenant_id, business_operation_id, event_type),
    CONSTRAINT fk_eos_outbox_operation
        FOREIGN KEY (tenant_id, business_operation_id)
        REFERENCES eos_business_operation (tenant_id, business_operation_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_outbox_event_type
        CHECK (event_type ~ '^[A-Z][A-Z0-9_]{0,127}$'),
    CONSTRAINT ck_eos_outbox_payload
        CHECK (jsonb_typeof(event_payload) = 'object'),
    CONSTRAINT ck_eos_outbox_payload_hash
        CHECK (event_payload_hash ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_eos_outbox_delivery_state
        CHECK (delivery_state IN ('PENDING', 'PUBLISHED')),
    CONSTRAINT ck_eos_outbox_attempt_count
        CHECK (attempt_count >= 0),
    CONSTRAINT ck_eos_outbox_published
        CHECK (
            (delivery_state = 'PENDING' AND published_at IS NULL)
            OR
            (delivery_state = 'PUBLISHED' AND published_at IS NOT NULL)
        )
);

CREATE INDEX IF NOT EXISTS ix_eos_outbox_pending
    ON eos_outbox (delivery_state, created_at, outbox_id);

CREATE INDEX IF NOT EXISTS ix_eos_outbox_operation
    ON eos_outbox (tenant_id, business_operation_id, created_at);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2501_eos_business_transaction_core',
    'NeX-EOS business operation, idempotency, and transactional outbox core'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
