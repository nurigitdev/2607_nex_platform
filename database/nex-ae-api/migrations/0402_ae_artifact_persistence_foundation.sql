BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_artifact_handoffs (
    artifact_handoff_id TEXT PRIMARY KEY,
    handoff_schema_version TEXT NOT NULL DEFAULT 'ae_artifact_handoff.v1'
        CHECK (handoff_schema_version = 'ae_artifact_handoff.v1'),
    artifact_request_id TEXT NOT NULL,
    handoff_status TEXT NOT NULL
        CHECK (handoff_status IN ('READY_FOR_RENDERING')),
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    chat_document_id TEXT NOT NULL,
    interaction_id TEXT NOT NULL,
    cx_generation_id TEXT NOT NULL,
    structured_draft_id TEXT NOT NULL,
    draft_schema_version TEXT NOT NULL
        CHECK (draft_schema_version = 'cx_structured_draft.v1'),
    structured_draft_content_hash TEXT NOT NULL
        CHECK (structured_draft_content_hash ~ '^[0-9a-f]{64}$'),
    citation_claims_hash TEXT NOT NULL
        CHECK (citation_claims_hash ~ '^[0-9a-f]{64}$'),
    validation_result_hash TEXT NOT NULL
        CHECK (validation_result_hash ~ '^[0-9a-f]{64}$'),
    template_id TEXT NULL,
    template_version TEXT NULL,
    rendering_template_id TEXT NULL,
    artifact_intent TEXT NOT NULL
        CHECK (artifact_intent IN ('preview_only', 'create_artifact', 'create_and_export')),
    target_formats JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(target_formats) = 'array'),
    artifact_title TEXT NOT NULL CHECK (char_length(artifact_title) <= 120),
    language TEXT NOT NULL CHECK (language IN ('ko', 'en')),
    retention_policy_ref TEXT NOT NULL,
    actor_claims_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(actor_claims_ref) = 'object'),
    workspace_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(workspace_ref) = 'object'),
    quality_summary JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(quality_summary) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ae_artifact_handoffs_request
    ON ae_artifact_handoffs (artifact_request_id);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_handoffs_owner_time
    ON ae_artifact_handoffs
    (tenant_id, workspace_id, owner_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_handoffs_interaction_time
    ON ae_artifact_handoffs (interaction_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_handoffs_generation
    ON ae_artifact_handoffs (cx_generation_id, structured_draft_id);

CREATE TABLE IF NOT EXISTS ae_artifacts (
    artifact_id TEXT PRIMARY KEY,
    artifact_schema_version TEXT NOT NULL DEFAULT 'ae_artifact_record.v1'
        CHECK (artifact_schema_version = 'ae_artifact_record.v1'),
    artifact_type TEXT NOT NULL
        CHECK (artifact_type IN ('generated_document', 'summary', 'answer_export')),
    artifact_status TEXT NOT NULL
        CHECK (artifact_status IN ('DRAFT', 'RENDERING', 'READY', 'FAILED', 'ARCHIVED', 'DELETED')),
    current_version_id TEXT NULL,
    artifact_handoff_id TEXT NOT NULL REFERENCES ae_artifact_handoffs(artifact_handoff_id)
        ON DELETE RESTRICT,
    artifact_request_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    chat_document_id TEXT NOT NULL,
    interaction_id TEXT NOT NULL,
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    display_title TEXT NOT NULL CHECK (char_length(display_title) <= 120),
    language TEXT NOT NULL CHECK (language IN ('ko', 'en')),
    artifact_intent TEXT NOT NULL
        CHECK (artifact_intent IN ('preview_only', 'create_artifact', 'create_and_export')),
    target_formats JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(target_formats) = 'array'),
    retention_policy_ref TEXT NOT NULL,
    owner_actor_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(owner_actor_ref) = 'object'),
    workspace_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(workspace_ref) = 'object'),
    template_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(template_ref) = 'object'),
    handoff_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(handoff_ref) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ae_artifacts_request
    ON ae_artifacts (artifact_request_id);

CREATE INDEX IF NOT EXISTS idx_ae_artifacts_owner_time
    ON ae_artifacts
    (tenant_id, workspace_id, owner_user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_artifacts_status_time
    ON ae_artifacts (artifact_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_artifacts_interaction_time
    ON ae_artifacts (interaction_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_artifacts_handoff
    ON ae_artifacts (artifact_handoff_id);

CREATE TABLE IF NOT EXISTS ae_artifact_source_refs (
    source_ref_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES ae_artifacts(artifact_id)
        ON DELETE CASCADE,
    cx_generation_id TEXT NOT NULL,
    structured_draft_id TEXT NOT NULL,
    draft_schema_version TEXT NOT NULL
        CHECK (draft_schema_version = 'cx_structured_draft.v1'),
    structured_draft_content_hash TEXT NOT NULL
        CHECK (structured_draft_content_hash ~ '^[0-9a-f]{64}$'),
    citation_claims_hash TEXT NOT NULL
        CHECK (citation_claims_hash ~ '^[0-9a-f]{64}$'),
    validation_result_hash TEXT NOT NULL
        CHECK (validation_result_hash ~ '^[0-9a-f]{64}$'),
    retrieval_package_id TEXT NULL,
    retrieval_package_hash TEXT NULL CHECK (
        retrieval_package_hash IS NULL
        OR retrieval_package_hash ~ '^[0-9a-f]{64}$'
    ),
    evidence_ref_count INTEGER NOT NULL DEFAULT 0 CHECK (evidence_ref_count >= 0),
    source_anchor_count INTEGER NOT NULL DEFAULT 0 CHECK (source_anchor_count >= 0),
    quality_summary JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(quality_summary) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ae_artifact_source_refs_artifact_generation
    ON ae_artifact_source_refs
    (artifact_id, cx_generation_id, structured_draft_id);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_source_refs_generation
    ON ae_artifact_source_refs (cx_generation_id, structured_draft_id);

CREATE TABLE IF NOT EXISTS ae_artifact_versions (
    artifact_version_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES ae_artifacts(artifact_id)
        ON DELETE CASCADE,
    version_no INTEGER NOT NULL CHECK (version_no >= 1),
    version_reason TEXT NOT NULL,
    source_generation_id TEXT NOT NULL,
    source_structured_draft_id TEXT NOT NULL,
    source_content_hash TEXT NOT NULL CHECK (source_content_hash ~ '^[0-9a-f]{64}$'),
    source_citation_claims_hash TEXT NOT NULL
        CHECK (source_citation_claims_hash ~ '^[0-9a-f]{64}$'),
    render_policy_hash TEXT NOT NULL CHECK (render_policy_hash ~ '^[0-9a-f]{64}$'),
    artifact_content_hash TEXT NOT NULL CHECK (artifact_content_hash ~ '^[0-9a-f]{64}$'),
    rendered_formats JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(rendered_formats) = 'array'),
    validation_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(validation_snapshot) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ae_artifact_versions_artifact_no
    ON ae_artifact_versions (artifact_id, version_no);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_versions_artifact_time
    ON ae_artifact_versions (artifact_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_versions_source_generation
    ON ae_artifact_versions (source_generation_id, source_structured_draft_id);

CREATE TABLE IF NOT EXISTS ae_artifact_render_jobs (
    render_job_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES ae_artifacts(artifact_id)
        ON DELETE CASCADE,
    artifact_version_id TEXT NULL REFERENCES ae_artifact_versions(artifact_version_id)
        ON DELETE SET NULL,
    job_status TEXT NOT NULL
        CHECK (job_status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
    current_stage TEXT NOT NULL,
    progress_mode TEXT NOT NULL CHECK (progress_mode IN ('DETERMINATE', 'INDETERMINATE')),
    progress_percent INTEGER NOT NULL CHECK (progress_percent >= 0 AND progress_percent <= 100),
    retryable BOOLEAN NOT NULL DEFAULT FALSE,
    failure_code TEXT NULL,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)
);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_render_jobs_artifact_time
    ON ae_artifact_render_jobs (artifact_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_render_jobs_status_time
    ON ae_artifact_render_jobs (job_status, updated_at DESC);

CREATE TABLE IF NOT EXISTS ae_artifact_files (
    artifact_file_id TEXT PRIMARY KEY,
    artifact_version_id TEXT NOT NULL REFERENCES ae_artifact_versions(artifact_version_id)
        ON DELETE CASCADE,
    artifact_id TEXT NOT NULL REFERENCES ae_artifacts(artifact_id)
        ON DELETE CASCADE,
    format TEXT NOT NULL CHECK (format IN ('MD', 'HTML_PREVIEW', 'DOCX', 'PDF')),
    mime_type TEXT NOT NULL,
    file_name TEXT NOT NULL CHECK (char_length(file_name) <= 255),
    storage_ref TEXT NOT NULL CHECK (storage_ref LIKE 'ae://artifacts/%'),
    file_size_bytes BIGINT NOT NULL CHECK (file_size_bytes >= 0),
    file_hash TEXT NOT NULL CHECK (file_hash ~ '^[0-9a-f]{64}$'),
    source_version_hash TEXT NOT NULL CHECK (source_version_hash ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ae_artifact_files_version_format
    ON ae_artifact_files (artifact_version_id, format);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_files_artifact
    ON ae_artifact_files (artifact_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_files_hash
    ON ae_artifact_files (file_hash);

CREATE TABLE IF NOT EXISTS ae_artifact_links (
    artifact_link_id TEXT PRIMARY KEY,
    artifact_file_id TEXT NOT NULL REFERENCES ae_artifact_files(artifact_file_id)
        ON DELETE CASCADE,
    link_type TEXT NOT NULL CHECK (link_type IN ('preview', 'download')),
    access_policy TEXT NOT NULL CHECK (access_policy IN ('owner_only')),
    link_route TEXT NOT NULL CHECK (link_route LIKE '/api/v1/artifact-files/%'),
    expires_at TIMESTAMPTZ NULL,
    created_by_actor_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(created_by_actor_ref) = 'object'),
    download_count INTEGER NOT NULL DEFAULT 0 CHECK (download_count >= 0),
    revoked_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ae_artifact_links_file_type
    ON ae_artifact_links (artifact_file_id, link_type);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_links_active_type
    ON ae_artifact_links (link_type, revoked_at, expires_at);

INSERT INTO schema_migrations (version, description)
VALUES ('0402_ae_artifact_persistence_foundation', 'AE artifact persistence schema foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
