BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_upload_handoffs (
    upload_handoff_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    cx_document_id TEXT NOT NULL,
    cx_upload_id TEXT NOT NULL,
    ingestion_job_id TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('QUEUED', 'ALREADY_EXISTS', 'PROCESSING', 'READY', 'FAILED')),
    record_payload JSONB NOT NULL CHECK (jsonb_typeof(record_payload) = 'object'),
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ae_upload_owner_time
    ON ae_upload_handoffs (tenant_id, owner_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_upload_ws_owner
    ON ae_upload_handoffs (workspace_id, tenant_id, owner_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_upload_cx_doc
    ON ae_upload_handoffs (cx_document_id, tenant_id, owner_user_id);

INSERT INTO schema_migrations (version, description)
VALUES (
    '1344_ae_upload_handoff_persistence',
    'AE owner-scoped durable upload handoff metadata'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
