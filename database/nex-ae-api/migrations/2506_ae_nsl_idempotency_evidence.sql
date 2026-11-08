BEGIN;

CREATE TABLE IF NOT EXISTS ae_nsl_idem_evidence (
    tenant_id TEXT NOT NULL
        CHECK (char_length(tenant_id) BETWEEN 1 AND 128),
    business_operation_id TEXT NOT NULL
        CHECK (char_length(business_operation_id) BETWEEN 1 AND 256),
    write_node_id TEXT NOT NULL
        CHECK (char_length(write_node_id) BETWEEN 1 AND 256),
    tool_id TEXT NOT NULL
        CHECK (char_length(tool_id) BETWEEN 1 AND 256),
    contract_hash TEXT NOT NULL
        CHECK (contract_hash ~ '^sha256:[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL
        CHECK (idempotency_key ~ '^idem:sha256:[0-9a-f]{64}$'),
    payload_hash TEXT NOT NULL
        CHECK (payload_hash ~ '^sha256:[0-9a-f]{64}$'),
    provider_guarantee_ref TEXT NOT NULL
        CHECK (char_length(provider_guarantee_ref) BETWEEN 1 AND 512),
    retained_until TIMESTAMPTZ NOT NULL,
    evidence_hash TEXT NOT NULL
        CHECK (evidence_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, idempotency_key),
    CONSTRAINT ux_ae_nsl_idem_business_node
        UNIQUE (tenant_id, business_operation_id, write_node_id)
);

CREATE INDEX IF NOT EXISTS ix_ae_nsl_idem_retention
    ON ae_nsl_idem_evidence (retained_until, tenant_id);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2506_ae_nsl_idempotency_evidence',
    'P8-S55 durable NSL execution idempotency evidence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
