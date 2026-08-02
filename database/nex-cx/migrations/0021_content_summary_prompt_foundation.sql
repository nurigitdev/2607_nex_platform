BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cx_source_blobs (
    source_blob_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_sha256 TEXT NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    content_type TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    first_seen_trace_id TEXT CHECK (first_seen_trace_id IS NULL OR first_seen_trace_id ~ '^[0-9a-f]{32}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_sha256)
);

CREATE TABLE IF NOT EXISTS cx_content_objects (
    content_object_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    source_blob_id UUID NOT NULL REFERENCES cx_source_blobs(source_blob_id),
    source_sha256 TEXT NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    upload_id UUID NOT NULL,
    original_filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    classification TEXT NOT NULL DEFAULT 'internal',
    lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (lifecycle_status IN ('ACTIVE', 'DELETED', 'QUARANTINED')),
    retrieval_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_trace_id TEXT CHECK (created_trace_id IS NULL OR created_trace_id ~ '^[0-9a-f]{32}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (upload_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_cx_content_owner_source_active
    ON cx_content_objects (tenant_id, owner_user_id, source_sha256)
    WHERE lifecycle_status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_cx_content_objects_owner
    ON cx_content_objects (tenant_id, owner_user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS cx_content_acl_entries (
    acl_entry_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_object_id UUID NOT NULL REFERENCES cx_content_objects(content_object_id) ON DELETE CASCADE,
    principal_type TEXT NOT NULL CHECK (principal_type IN ('user', 'group', 'service')),
    principal_id TEXT NOT NULL,
    permission TEXT NOT NULL CHECK (permission IN ('read', 'comment', 'write', 'owner')),
    granted_by_user_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (content_object_id, principal_type, principal_id, permission)
);

CREATE TABLE IF NOT EXISTS cx_extraction_artifacts (
    extraction_artifact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_object_id UUID NOT NULL REFERENCES cx_content_objects(content_object_id) ON DELETE CASCADE,
    source_blob_id UUID NOT NULL REFERENCES cx_source_blobs(source_blob_id),
    artifact_kind TEXT NOT NULL DEFAULT 'markdown' CHECK (artifact_kind = 'markdown'),
    status TEXT NOT NULL DEFAULT 'SUCCEEDED'
        CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')),
    extractor_name TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    markdown_sha256 TEXT NOT NULL CHECK (markdown_sha256 ~ '^[0-9a-f]{64}$'),
    markdown_storage_uri TEXT NOT NULL,
    markdown_char_count INTEGER NOT NULL CHECK (markdown_char_count >= 0),
    created_trace_id TEXT CHECK (created_trace_id IS NULL OR created_trace_id ~ '^[0-9a-f]{32}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (content_object_id, extractor_name, extractor_version, markdown_sha256)
);

CREATE TABLE IF NOT EXISTS cx_chunk_sets (
    chunk_set_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_object_id UUID NOT NULL REFERENCES cx_content_objects(content_object_id) ON DELETE CASCADE,
    extraction_artifact_id UUID NOT NULL REFERENCES cx_extraction_artifacts(extraction_artifact_id) ON DELETE CASCADE,
    chunk_policy_id TEXT NOT NULL,
    chunk_size INTEGER NOT NULL CHECK (chunk_size > 0),
    chunk_overlap INTEGER NOT NULL CHECK (chunk_overlap >= 0 AND chunk_overlap < chunk_size),
    source_markdown_sha256 TEXT NOT NULL CHECK (source_markdown_sha256 ~ '^[0-9a-f]{64}$'),
    chunk_count INTEGER NOT NULL CHECK (chunk_count >= 0),
    created_trace_id TEXT CHECK (created_trace_id IS NULL OR created_trace_id ~ '^[0-9a-f]{32}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (content_object_id, extraction_artifact_id, chunk_policy_id, source_markdown_sha256)
);

CREATE TABLE IF NOT EXISTS cx_chunks (
    chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_set_id UUID NOT NULL REFERENCES cx_chunk_sets(chunk_set_id) ON DELETE CASCADE,
    content_object_id UUID NOT NULL REFERENCES cx_content_objects(content_object_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
    end_offset INTEGER NOT NULL CHECK (end_offset >= start_offset),
    char_count INTEGER NOT NULL CHECK (char_count >= 0),
    text_sha256 TEXT NOT NULL CHECK (text_sha256 ~ '^[0-9a-f]{64}$'),
    text_preview TEXT NOT NULL CHECK (char_length(text_preview) <= 240),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chunk_set_id, ordinal),
    UNIQUE (chunk_set_id, text_sha256)
);

CREATE TABLE IF NOT EXISTS cx_chunk_embeddings (
    chunk_embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id UUID NOT NULL REFERENCES cx_chunks(chunk_id) ON DELETE CASCADE,
    provider_alias TEXT NOT NULL,
    model_profile_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    vector_dimension INTEGER NOT NULL CHECK (vector_dimension > 0),
    embedding_sha256 TEXT NOT NULL CHECK (embedding_sha256 ~ '^[0-9a-f]{64}$'),
    embedding_storage_uri TEXT,
    status TEXT NOT NULL DEFAULT 'READY' CHECK (status IN ('READY', 'STALE', 'FAILED')),
    created_trace_id TEXT CHECK (created_trace_id IS NULL OR created_trace_id ~ '^[0-9a-f]{32}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chunk_id, model_profile_id, model_revision)
);

CREATE TABLE IF NOT EXISTS cx_lexical_terms (
    lexical_term_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_set_id UUID NOT NULL REFERENCES cx_chunk_sets(chunk_set_id) ON DELETE CASCADE,
    tokenizer_requested TEXT NOT NULL,
    tokenizer_used TEXT NOT NULL,
    tokenizer_fallback TEXT NOT NULL,
    fallback_used BOOLEAN NOT NULL DEFAULT false,
    term TEXT NOT NULL,
    document_frequency INTEGER NOT NULL CHECK (document_frequency >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chunk_set_id, tokenizer_used, term)
);

CREATE TABLE IF NOT EXISTS cx_lexical_postings (
    lexical_posting_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lexical_term_id UUID NOT NULL REFERENCES cx_lexical_terms(lexical_term_id) ON DELETE CASCADE,
    chunk_id UUID NOT NULL REFERENCES cx_chunks(chunk_id) ON DELETE CASCADE,
    occurrence_count INTEGER NOT NULL CHECK (occurrence_count > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (lexical_term_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS cx_prompt_templates (
    prompt_template_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_id TEXT NOT NULL DEFAULT 'nex-cx' CHECK (service_id = 'nex-cx'),
    purpose TEXT NOT NULL,
    name TEXT NOT NULL,
    owner_domain TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'ACTIVE', 'RETIRED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (service_id, purpose, name)
);

CREATE TABLE IF NOT EXISTS cx_prompt_template_versions (
    prompt_template_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_template_id UUID NOT NULL REFERENCES cx_prompt_templates(prompt_template_id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('system', 'developer', 'user_prefix', 'user_suffix', 'repair', 'evaluation')),
    segment_order INTEGER NOT NULL DEFAULT 0 CHECK (segment_order >= 0),
    content TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    model_capability TEXT NOT NULL CHECK (model_capability IN ('generation', 'summary', 'classification')),
    summary_max_chars INTEGER CHECK (summary_max_chars IS NULL OR (summary_max_chars > 0 AND summary_max_chars <= 1000)),
    summary_hard_limit_chars INTEGER CHECK (summary_hard_limit_chars IS NULL OR (summary_hard_limit_chars > 0 AND summary_hard_limit_chars <= 1000)),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'RETIRED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (prompt_template_id, version, role, segment_order)
);

CREATE TABLE IF NOT EXISTS cx_prompt_bindings (
    prompt_binding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    binding_key TEXT NOT NULL UNIQUE,
    prompt_template_version_id UUID NOT NULL REFERENCES cx_prompt_template_versions(prompt_template_version_id),
    service_id TEXT NOT NULL DEFAULT 'nex-cx' CHECK (service_id = 'nex-cx'),
    purpose TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'DISABLED')),
    bound_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cx_prompt_render_events (
    prompt_render_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_binding_id UUID REFERENCES cx_prompt_bindings(prompt_binding_id),
    prompt_template_version_id UUID REFERENCES cx_prompt_template_versions(prompt_template_version_id),
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    rendered_prompt_hash TEXT NOT NULL CHECK (rendered_prompt_hash ~ '^[0-9a-f]{64}$'),
    rendered_prompt_preview TEXT CHECK (rendered_prompt_preview IS NULL OR char_length(rendered_prompt_preview) <= 240),
    user_prompt_hash TEXT CHECK (user_prompt_hash IS NULL OR user_prompt_hash ~ '^[0-9a-f]{64}$'),
    output_hash TEXT CHECK (output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cx_document_summaries (
    document_summary_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_object_id UUID NOT NULL REFERENCES cx_content_objects(content_object_id) ON DELETE CASCADE,
    extraction_artifact_id UUID NOT NULL REFERENCES cx_extraction_artifacts(extraction_artifact_id) ON DELETE CASCADE,
    prompt_template_version_id UUID REFERENCES cx_prompt_template_versions(prompt_template_version_id),
    summary_chunk_policy_id TEXT NOT NULL DEFAULT 'summary_1000_0',
    summary_text_sha256 TEXT NOT NULL CHECK (summary_text_sha256 ~ '^[0-9a-f]{64}$'),
    summary_storage_uri TEXT NOT NULL,
    summary_char_count INTEGER NOT NULL CHECK (summary_char_count >= 0),
    summary_max_chars INTEGER NOT NULL DEFAULT 900 CHECK (summary_max_chars > 0 AND summary_max_chars <= 1000),
    summary_hard_limit_chars INTEGER NOT NULL DEFAULT 1000 CHECK (summary_hard_limit_chars > 0 AND summary_hard_limit_chars <= 1000),
    status TEXT NOT NULL DEFAULT 'READY' CHECK (status IN ('PENDING', 'RUNNING', 'READY', 'REPAIR_REQUIRED', 'FAILED')),
    language_code TEXT,
    model_profile_id TEXT,
    model_revision TEXT,
    created_trace_id TEXT CHECK (created_trace_id IS NULL OR created_trace_id ~ '^[0-9a-f]{32}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (summary_char_count <= summary_hard_limit_chars),
    UNIQUE (content_object_id, extraction_artifact_id, summary_text_sha256)
);

CREATE TABLE IF NOT EXISTS cx_document_summary_embeddings (
    summary_embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_summary_id UUID NOT NULL REFERENCES cx_document_summaries(document_summary_id) ON DELETE CASCADE,
    provider_alias TEXT NOT NULL,
    model_profile_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    vector_dimension INTEGER NOT NULL CHECK (vector_dimension > 0),
    embedding_sha256 TEXT NOT NULL CHECK (embedding_sha256 ~ '^[0-9a-f]{64}$'),
    embedding_storage_uri TEXT,
    status TEXT NOT NULL DEFAULT 'READY' CHECK (status IN ('READY', 'STALE', 'FAILED')),
    created_trace_id TEXT CHECK (created_trace_id IS NULL OR created_trace_id ~ '^[0-9a-f]{32}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_summary_id, model_profile_id, model_revision)
);

CREATE INDEX IF NOT EXISTS idx_cx_document_summaries_content
    ON cx_document_summaries (content_object_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_cx_summary_embeddings_summary
    ON cx_document_summary_embeddings (document_summary_id, status);

INSERT INTO schema_migrations (version, description)
VALUES ('0021_content_summary_prompt_foundation', 'CX content, summary, embedding, and prompt registry foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
