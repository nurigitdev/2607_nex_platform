BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE ae_chat_interactions
    ADD COLUMN IF NOT EXISTS interaction_schema_version TEXT NOT NULL
        DEFAULT 'ae_chat_interaction.v1'
        CHECK (interaction_schema_version = 'ae_chat_interaction.v1');

ALTER TABLE ae_chat_interactions
    ADD COLUMN IF NOT EXISTS failure_summary JSONB NOT NULL
        DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(failure_summary) = 'object');

CREATE TABLE IF NOT EXISTS ae_chat_artifact_refs (
    chat_artifact_ref_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_interaction_id UUID NOT NULL REFERENCES ae_chat_interactions(chat_interaction_id)
        ON DELETE CASCADE,
    chat_document_id UUID NOT NULL,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_version_id TEXT NOT NULL,
    display_title TEXT NOT NULL CHECK (char_length(display_title) <= 120),
    artifact_type TEXT NOT NULL
        CHECK (artifact_type IN ('generated_document', 'summary', 'answer_export')),
    artifact_status TEXT NOT NULL
        CHECK (artifact_status IN ('DRAFT', 'RENDERING', 'READY', 'FAILED', 'ARCHIVED', 'DELETED')),
    primary_format TEXT NOT NULL CHECK (primary_format IN ('MD', 'HTML_PREVIEW', 'DOCX', 'PDF')),
    available_formats JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(available_formats) = 'array'),
    preview_route TEXT CHECK (
        preview_route IS NULL
        OR preview_route LIKE '/api/v1/artifact-files/%/preview'
    ),
    download_routes JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(download_routes) = 'object'),
    source_generation_id TEXT NOT NULL,
    source_content_hash TEXT NOT NULL CHECK (source_content_hash ~ '^[0-9a-f]{64}$'),
    quality_summary JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(quality_summary) = 'object'),
    actions JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(actions) = 'array'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chat_interaction_id, artifact_id, artifact_version_id)
);

CREATE INDEX IF NOT EXISTS idx_ae_chat_artifact_refs_owner_time
    ON ae_chat_artifact_refs (tenant_id, user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_chat_artifact_refs_chat_time
    ON ae_chat_artifact_refs (chat_interaction_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_chat_artifact_refs_artifact
    ON ae_chat_artifact_refs (artifact_id, artifact_version_id);

CREATE INDEX IF NOT EXISTS idx_ae_chat_artifact_refs_generation
    ON ae_chat_artifact_refs (source_generation_id);

INSERT INTO schema_migrations (version, description)
VALUES (
    '0407_ae_chat_artifact_refs_foundation',
    'AE chat interaction artifact reference persistence foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
