BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ag_op_notes (
    operator_note_id TEXT PRIMARY KEY,
    operator_note_schema_version TEXT NOT NULL DEFAULT 'ag_operator_review_note.v1'
        CHECK (operator_note_schema_version = 'ag_operator_review_note.v1'),
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
    note_status TEXT NOT NULL CHECK (
        note_status IN ('ACTIVE', 'SUPERSEDED', 'RESOLVED', 'DELETED')
    ),
    note_type TEXT NOT NULL CHECK (
        note_type IN ('OBSERVATION', 'ACTION', 'FOLLOW_UP', 'ESCALATION', 'RESOLUTION')
    ),
    severity TEXT NOT NULL CHECK (
        severity IN ('INFO', 'LOW', 'MEDIUM', 'HIGH', 'URGENT')
    ),
    operator_note_hash TEXT NOT NULL
        CHECK (operator_note_hash ~ '^[0-9a-f]{64}$'),
    operator_note_preview TEXT NOT NULL
        CHECK (char_length(operator_note_preview) <= 240),
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(reason_codes) = 'array'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ag_op_notes_target_time
    ON ag_op_notes (target_service, target_kind, target_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_op_notes_trace_time
    ON ag_op_notes (trace_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_op_notes_operator_time
    ON ag_op_notes (operator_type, operator_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_op_notes_status_time
    ON ag_op_notes (note_status, updated_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('0622_ag_operator_review_note_persistence', 'AG operator review note persistence foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
