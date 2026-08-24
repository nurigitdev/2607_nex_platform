BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ag_generation_quality_operator_dispositions (
    disposition_id TEXT PRIMARY KEY,
    disposition_schema_version TEXT NOT NULL DEFAULT 'ag_generation_quality_operator_disposition.v1'
        CHECK (disposition_schema_version = 'ag_generation_quality_operator_disposition.v1'),
    cx_generation_id TEXT NOT NULL,
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    operator_type TEXT NOT NULL CHECK (operator_type IN ('service', 'user')),
    operator_id TEXT NOT NULL,
    tenant_id TEXT,
    operator_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(operator_ref) = 'object'),
    operator_action TEXT NOT NULL CHECK (
        operator_action IN (
            'acknowledged',
            'false_positive',
            'needs_cx_repair',
            'needs_ae_followup',
            'escalated',
            'resolved'
        )
    ),
    disposition_status TEXT NOT NULL CHECK (
        disposition_status IN (
            'ACKNOWLEDGED',
            'DISMISSED',
            'IN_REPAIR',
            'ESCALATED',
            'RESOLVED'
        )
    ),
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(reason_codes) = 'array'),
    operator_note_hash TEXT
        CHECK (operator_note_hash IS NULL OR operator_note_hash ~ '^[0-9a-f]{64}$'),
    operator_note_preview TEXT
        CHECK (operator_note_preview IS NULL OR char_length(operator_note_preview) <= 240),
    quality_issue_refs JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(quality_issue_refs) = 'array'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ag_generation_quality_dispositions_generation_time
    ON ag_generation_quality_operator_dispositions (cx_generation_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_generation_quality_dispositions_operator_time
    ON ag_generation_quality_operator_dispositions (operator_type, operator_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_generation_quality_dispositions_status_time
    ON ag_generation_quality_operator_dispositions (disposition_status, updated_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('0337_ag_generation_quality_operator_disposition_persistence', 'AG generation quality operator disposition persistence foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
