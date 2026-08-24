BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_generation_feedback (
    feedback_id TEXT PRIMARY KEY,
    feedback_schema_version TEXT NOT NULL DEFAULT 'ae_generation_feedback.v1'
        CHECK (feedback_schema_version = 'ae_generation_feedback.v1'),
    status TEXT NOT NULL CHECK (status IN ('RECORDED', 'REJECTED')),
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    interaction_id TEXT NOT NULL,
    chat_document_id TEXT,
    cx_generation_id TEXT,
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    feedback_value TEXT NOT NULL CHECK (feedback_value IN ('positive', 'negative', 'neutral')),
    feedback_reasons JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(feedback_reasons) = 'array'),
    feedback_comment_hash TEXT
        CHECK (feedback_comment_hash IS NULL OR feedback_comment_hash ~ '^[0-9a-f]{64}$'),
    feedback_comment_preview TEXT
        CHECK (feedback_comment_preview IS NULL OR char_length(feedback_comment_preview) <= 240),
    quality_issue_refs JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(quality_issue_refs) = 'array'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ae_generation_feedback_user_time
    ON ae_generation_feedback (tenant_id, user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_generation_feedback_interaction_time
    ON ae_generation_feedback (interaction_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_generation_feedback_cx_generation
    ON ae_generation_feedback (cx_generation_id)
    WHERE cx_generation_id IS NOT NULL;

INSERT INTO schema_migrations (version, description)
VALUES ('0334_ae_generation_feedback_persistence', 'AE generation feedback persistence foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
