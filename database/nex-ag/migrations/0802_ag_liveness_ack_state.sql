BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ag_op_review_ack_state (
    ack_state_id TEXT PRIMARY KEY,
    ack_state_schema_version TEXT NOT NULL DEFAULT 'ag_operator_review_escalation_dispatch_daemon_liveness_ack_state.v1'
        CHECK (
            ack_state_schema_version = 'ag_operator_review_escalation_dispatch_daemon_liveness_ack_state.v1'
        ),
    acknowledgement_key TEXT NOT NULL,
    service_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    worker_type TEXT NOT NULL,
    liveness_status TEXT NOT NULL CHECK (
        liveness_status IN (
            'MISSING',
            'STALE',
            'SOURCE_NOT_CONFIGURED',
            'SOURCE_UNAVAILABLE'
        )
    ),
    action TEXT NOT NULL CHECK (
        action IN (
            'acknowledge_once',
            'suppress_for_ttl',
            'acknowledge_source_attention',
            'suppress_source_attention_for_ttl',
            'clear'
        )
    ),
    state_status TEXT NOT NULL CHECK (
        state_status IN ('ACKNOWLEDGED', 'SUPPRESSED', 'EXPIRED', 'CLEARED')
    ),
    operator_type TEXT NOT NULL CHECK (operator_type IN ('service', 'user')),
    operator_id TEXT NOT NULL,
    tenant_id TEXT,
    operator_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(operator_ref) = 'object'),
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(reason_codes) = 'array'),
    comment_hash TEXT CHECK (
        comment_hash IS NULL OR comment_hash ~ '^[0-9a-f]{64}$'
    ),
    comment_preview TEXT CHECK (
        comment_preview IS NULL OR char_length(comment_preview) <= 240
    ),
    idempotency_key_hash TEXT CHECK (
        idempotency_key_hash IS NULL OR idempotency_key_hash ~ '^[0-9a-f]{64}$'
    ),
    requested_ttl_seconds INTEGER CHECK (
        requested_ttl_seconds IS NULL OR requested_ttl_seconds > 0
    ),
    suppressed_until TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    cleared_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ag_ack_state_key
    ON ag_op_review_ack_state (acknowledgement_key);

CREATE INDEX IF NOT EXISTS idx_ag_ack_state_status_time
    ON ag_op_review_ack_state (state_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_ack_state_worker_time
    ON ag_op_review_ack_state (service_id, worker_id, updated_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('0802_ag_liveness_ack_state', 'AG dispatch liveness acknowledgement/suppression state foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
