BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ag_op_escalations (
    escalation_id TEXT PRIMARY KEY,
    escalation_schema_version TEXT NOT NULL DEFAULT 'ag_operator_review_escalation.v1'
        CHECK (escalation_schema_version = 'ag_operator_review_escalation.v1'),
    candidate_id TEXT NOT NULL,
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
    assignment_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(assignment_ref) = 'object'),
    escalation_status TEXT NOT NULL CHECK (
        escalation_status IN (
            'ACTIVE',
            'ACKNOWLEDGED',
            'SNOOZED',
            'DISMISSED',
            'RESOLVED',
            'REOPENED'
        )
    ),
    escalation_level TEXT NOT NULL CHECK (
        escalation_level IN ('OBSERVE', 'FOLLOW_UP', 'ATTENTION', 'BLOCKED')
    ),
    sla_state TEXT NOT NULL CHECK (
        sla_state IN ('WATCH', 'WARNING', 'OVERDUE', 'ATTENTION')
    ),
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(reason_codes) = 'array'),
    runbook_ids JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(runbook_ids) = 'array'),
    recommended_actions JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(recommended_actions) = 'array'),
    last_action_type TEXT,
    last_action_at TIMESTAMPTZ,
    snoozed_until TIMESTAMPTZ,
    comment_hash TEXT CHECK (
        comment_hash IS NULL OR comment_hash ~ '^[0-9a-f]{64}$'
    ),
    comment_preview TEXT CHECK (
        comment_preview IS NULL OR char_length(comment_preview) <= 240
    ),
    idempotency_key_hash TEXT CHECK (
        idempotency_key_hash IS NULL OR idempotency_key_hash ~ '^[0-9a-f]{64}$'
    ),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ag_op_escalations_candidate
    ON ag_op_escalations (candidate_id);

CREATE INDEX IF NOT EXISTS idx_ag_op_escalations_case_time
    ON ag_op_escalations (case_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_op_escalations_status_time
    ON ag_op_escalations (escalation_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_op_escalations_target_time
    ON ag_op_escalations (target_service, target_kind, target_id, updated_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('0692_ag_operator_review_escalation_persistence', 'AG operator review escalation persistence foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
