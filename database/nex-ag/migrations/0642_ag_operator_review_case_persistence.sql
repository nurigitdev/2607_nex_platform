BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ag_op_cases (
    case_id TEXT PRIMARY KEY,
    case_schema_version TEXT NOT NULL DEFAULT 'ag_operator_review_case.v1'
        CHECK (case_schema_version = 'ag_operator_review_case.v1'),
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
    case_status TEXT NOT NULL CHECK (
        case_status IN (
            'OPEN',
            'ACKNOWLEDGED',
            'ASSIGNED',
            'RESOLVED',
            'DISMISSED',
            'REOPENED'
        )
    ),
    case_priority TEXT NOT NULL CHECK (
        case_priority IN ('LOW', 'MEDIUM', 'HIGH', 'URGENT')
    ),
    source_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(source_ref) = 'object'),
    assignment_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(assignment_ref) = 'object'),
    assignee_id TEXT,
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(reason_codes) = 'array'),
    resolution_hash TEXT CHECK (
        resolution_hash IS NULL OR resolution_hash ~ '^[0-9a-f]{64}$'
    ),
    resolution_preview TEXT CHECK (
        resolution_preview IS NULL OR char_length(resolution_preview) <= 240
    ),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ag_op_cases_target_time
    ON ag_op_cases (target_service, target_kind, target_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_op_cases_trace_time
    ON ag_op_cases (trace_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_op_cases_status_time
    ON ag_op_cases (case_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_op_cases_assignee_time
    ON ag_op_cases (assignee_id, updated_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('0642_ag_operator_review_case_persistence', 'AG operator review case persistence foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
