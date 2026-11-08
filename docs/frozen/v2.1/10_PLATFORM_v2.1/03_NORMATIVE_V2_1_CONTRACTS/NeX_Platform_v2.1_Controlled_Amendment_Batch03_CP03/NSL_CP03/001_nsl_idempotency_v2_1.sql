-- NeX NSL v0.2 / Platform v2.1 durable idempotency ledger
CREATE TABLE IF NOT EXISTS nsl_idempotency_record (
    tenant_id                  text        NOT NULL,
    idempotency_key            text        NOT NULL,
    business_operation_id      text        NOT NULL,
    write_node_id              text        NOT NULL,
    payload_hash               text        NOT NULL,
    write_intent_hash          text        NULL,
    state                      text        NOT NULL,
    original_nsl_execution_id  text        NULL,
    original_result_ref        text        NULL,
    provider_transaction_ref   text        NULL,
    business_reference         text        NULL,
    last_error_ref             text        NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, idempotency_key),
    UNIQUE (tenant_id, business_operation_id, write_node_id)
);

-- Contract:
-- same key + same payload_hash     => REPLAY_OR_CONTINUE original record
-- same key + different payload_hash => IDEMPOTENCY_CONFLICT; Provider WRITE = 0
