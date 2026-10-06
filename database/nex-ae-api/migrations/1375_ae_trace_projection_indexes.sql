BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ae_upload_trace
    ON ae_upload_handoffs (trace_id, updated_at ASC);

CREATE INDEX IF NOT EXISTS idx_ae_chat_trace
    ON ae_chat_interactions (trace_id, updated_at ASC);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_trace
    ON ae_artifacts (trace_id, updated_at ASC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '1375_ae_trace_projection_indexes',
    'AE upload response and artifact trace projection indexes'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
