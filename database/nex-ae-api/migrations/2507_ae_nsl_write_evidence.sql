BEGIN;

CREATE TABLE IF NOT EXISTS ae_nsl_write_evidence (
    tenant_id TEXT NOT NULL
        CHECK (char_length(tenant_id) BETWEEN 1 AND 128),
    nsl_execution_id TEXT NOT NULL
        CHECK (char_length(nsl_execution_id) BETWEEN 1 AND 256),
    business_operation_id TEXT NOT NULL
        CHECK (char_length(business_operation_id) BETWEEN 1 AND 256),
    invocation_id TEXT NOT NULL
        CHECK (char_length(invocation_id) BETWEEN 1 AND 256),
    write_node_id TEXT NOT NULL
        CHECK (char_length(write_node_id) BETWEEN 1 AND 256),
    tool_id TEXT NOT NULL
        CHECK (char_length(tool_id) BETWEEN 1 AND 256),
    contract_hash TEXT NOT NULL
        CHECK (contract_hash ~ '^sha256:[0-9a-f]{64}$'),
    approval_request_id TEXT NOT NULL
        CHECK (char_length(approval_request_id) BETWEEN 1 AND 256),
    idempotency_key TEXT NOT NULL
        CHECK (idempotency_key ~ '^idem:sha256:[0-9a-f]{64}$'),
    payload_hash TEXT NOT NULL
        CHECK (payload_hash ~ '^sha256:[0-9a-f]{64}$'),
    write_intent_hash TEXT NOT NULL
        CHECK (write_intent_hash ~ '^sha256:[0-9a-f]{64}$'),
    precondition_evidence_id TEXT NOT NULL
        CHECK (char_length(precondition_evidence_id) BETWEEN 1 AND 256),
    requested_at TIMESTAMPTZ NOT NULL,
    record_hash TEXT NOT NULL
        CHECK (record_hash ~ '^sha256:[0-9a-f]{64}$'),
    persisted_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, nsl_execution_id, invocation_id),
    CONSTRAINT ux_ae_nsl_write_record
        UNIQUE (tenant_id, record_hash),
    CONSTRAINT ck_ae_nsl_write_persisted_after_request
        CHECK (persisted_at >= requested_at)
);

CREATE INDEX IF NOT EXISTS ix_ae_nsl_write_operation
    ON ae_nsl_write_evidence (
        tenant_id, business_operation_id, write_node_id, requested_at
    );

CREATE INDEX IF NOT EXISTS ix_ae_nsl_write_idempotency
    ON ae_nsl_write_evidence (tenant_id, idempotency_key);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2507_ae_nsl_write_evidence',
    'P8-S56 durable NSL WRITE_REQUESTED evidence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
