BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ag_op_esc_dispatches (
    dispatch_id TEXT PRIMARY KEY,
    dispatch_schema_version TEXT NOT NULL DEFAULT 'ag_operator_review_escalation_dispatch.v1'
        CHECK (dispatch_schema_version = 'ag_operator_review_escalation_dispatch.v1'),
    escalation_id TEXT NOT NULL REFERENCES ag_op_escalations(escalation_id) ON DELETE CASCADE,
    case_id TEXT NOT NULL REFERENCES ag_op_cases(case_id) ON DELETE CASCADE,
    target_service TEXT NOT NULL CHECK (
        target_service IN ('nex-ae-api', 'nex-cx', 'nex-mo', 'nex-oa', 'nex-ag')
    ),
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    trace_id TEXT CHECK (trace_id IS NULL OR trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    operator_type TEXT NOT NULL CHECK (operator_type IN ('service', 'user')),
    operator_id TEXT NOT NULL,
    tenant_id TEXT,
    operator_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(operator_ref) = 'object'),
    channel_type TEXT NOT NULL CHECK (
        channel_type IN ('MOCK', 'NOTIFICATION', 'EMAIL', 'WEBHOOK', 'INCIDENT')
    ),
    provider_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(provider_ref) = 'object'),
    provider_profile TEXT NOT NULL,
    dispatch_status TEXT NOT NULL CHECK (
        dispatch_status IN (
            'PENDING',
            'DISPATCHING',
            'SUCCEEDED',
            'FAILED',
            'RETRY_WAIT',
            'CANCELLED'
        )
    ),
    dispatch_intent TEXT NOT NULL CHECK (
        dispatch_intent IN (
            'NOTIFY_OPERATOR',
            'NOTIFY_OWNER',
            'OPEN_INCIDENT',
            'UPDATE_INCIDENT',
            'CANCEL_PENDING_DISPATCH',
            'RETRY_FAILED_DISPATCH'
        )
    ),
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(reason_codes) = 'array'),
    safe_subject TEXT CHECK (
        safe_subject IS NULL OR char_length(safe_subject) <= 200
    ),
    safe_body_hash TEXT CHECK (
        safe_body_hash IS NULL OR safe_body_hash ~ '^[0-9a-f]{64}$'
    ),
    safe_body_preview TEXT CHECK (
        safe_body_preview IS NULL OR char_length(safe_body_preview) <= 240
    ),
    provider_payload_hash TEXT CHECK (
        provider_payload_hash IS NULL OR provider_payload_hash ~ '^[0-9a-f]{64}$'
    ),
    idempotency_key_hash TEXT CHECK (
        idempotency_key_hash IS NULL OR idempotency_key_hash ~ '^[0-9a-f]{64}$'
    ),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_attempt_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ,
    last_error_code TEXT,
    last_error_hash TEXT CHECK (
        last_error_hash IS NULL OR last_error_hash ~ '^[0-9a-f]{64}$'
    ),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ag_op_esc_dispatches_escalation_time
    ON ag_op_esc_dispatches (escalation_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_op_esc_dispatches_case_time
    ON ag_op_esc_dispatches (case_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_op_esc_dispatches_status_time
    ON ag_op_esc_dispatches (dispatch_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_op_esc_dispatches_target_time
    ON ag_op_esc_dispatches (target_service, target_kind, target_id, updated_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('0702_ag_operator_review_escalation_dispatch', 'AG operator review escalation dispatch outbox foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
