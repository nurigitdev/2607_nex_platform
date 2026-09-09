BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ag_ev_exports (
    export_id TEXT PRIMARY KEY,
    export_schema_version TEXT NOT NULL DEFAULT 'ag_redacted_evidence_export.v1'
        CHECK (export_schema_version = 'ag_redacted_evidence_export.v1'),
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
    export_status TEXT NOT NULL CHECK (
        export_status IN ('REQUESTED', 'READY', 'FAILED', 'CANCELLED')
    ),
    export_format TEXT NOT NULL CHECK (
        export_format IN ('json', 'jsonl', 'zip_manifest')
    ),
    redaction_profile TEXT NOT NULL DEFAULT 'ag_redacted_manifest_v1',
    evidence_manifest JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(evidence_manifest) = 'object'),
    evidence_hash TEXT NOT NULL CHECK (evidence_hash ~ '^[0-9a-f]{64}$'),
    evidence_item_count INTEGER NOT NULL CHECK (evidence_item_count >= 0),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ag_ev_exports_target_time
    ON ag_ev_exports (target_service, target_kind, target_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_ev_exports_trace_time
    ON ag_ev_exports (trace_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_ev_exports_operator_time
    ON ag_ev_exports (operator_type, operator_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_ev_exports_status_time
    ON ag_ev_exports (export_status, updated_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('0626_ag_redacted_evidence_export_persistence', 'AG redacted evidence export persistence foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
