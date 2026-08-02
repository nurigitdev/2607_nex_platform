BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_chat_interactions (
    chat_interaction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    chat_document_id UUID NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'COMPLETED', 'NO_ANSWER', 'FAILED')),
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    user_message_hash TEXT NOT NULL CHECK (user_message_hash ~ '^[0-9a-f]{64}$'),
    user_message_preview TEXT NOT NULL CHECK (char_length(user_message_preview) <= 240),
    cx_retrieval_package_id TEXT,
    cx_retrieval_package_hash TEXT CHECK (cx_retrieval_package_hash IS NULL OR cx_retrieval_package_hash ~ '^[0-9a-f]{64}$'),
    cx_generation_id TEXT,
    cx_generation_status TEXT,
    retrieval_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    generation_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ae_chat_interactions_user
    ON ae_chat_interactions (tenant_id, user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ae_prompt_templates (
    prompt_template_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_id TEXT NOT NULL DEFAULT 'nex-ae-api' CHECK (service_id = 'nex-ae-api'),
    purpose TEXT NOT NULL,
    name TEXT NOT NULL,
    owner_domain TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'ACTIVE', 'RETIRED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (service_id, purpose, name)
);

CREATE TABLE IF NOT EXISTS ae_prompt_template_versions (
    prompt_template_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_template_id UUID NOT NULL REFERENCES ae_prompt_templates(prompt_template_id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('system', 'developer', 'user_prefix', 'user_suffix', 'repair', 'evaluation')),
    segment_order INTEGER NOT NULL DEFAULT 0 CHECK (segment_order >= 0),
    content TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    model_capability TEXT NOT NULL CHECK (model_capability IN ('generation', 'summary', 'classification', 'recommendation')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'RETIRED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (prompt_template_id, version, role, segment_order)
);

CREATE TABLE IF NOT EXISTS ae_prompt_bindings (
    prompt_binding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    binding_key TEXT NOT NULL UNIQUE,
    prompt_template_version_id UUID NOT NULL REFERENCES ae_prompt_template_versions(prompt_template_version_id),
    service_id TEXT NOT NULL DEFAULT 'nex-ae-api' CHECK (service_id = 'nex-ae-api'),
    purpose TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'DISABLED')),
    bound_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_prompt_render_events (
    prompt_render_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_binding_id UUID REFERENCES ae_prompt_bindings(prompt_binding_id),
    prompt_template_version_id UUID REFERENCES ae_prompt_template_versions(prompt_template_version_id),
    chat_interaction_id UUID REFERENCES ae_chat_interactions(chat_interaction_id) ON DELETE SET NULL,
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    rendered_prompt_hash TEXT NOT NULL CHECK (rendered_prompt_hash ~ '^[0-9a-f]{64}$'),
    rendered_prompt_preview TEXT CHECK (rendered_prompt_preview IS NULL OR char_length(rendered_prompt_preview) <= 240),
    user_prompt_hash TEXT CHECK (user_prompt_hash IS NULL OR user_prompt_hash ~ '^[0-9a-f]{64}$'),
    output_hash TEXT CHECK (output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_prompt_events (
    prompt_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    chat_interaction_id UUID REFERENCES ae_chat_interactions(chat_interaction_id) ON DELETE SET NULL,
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    prompt_hash TEXT NOT NULL CHECK (prompt_hash ~ '^[0-9a-f]{64}$'),
    prompt_preview TEXT NOT NULL CHECK (char_length(prompt_preview) <= 240),
    prompt_char_count INTEGER NOT NULL CHECK (prompt_char_count >= 0),
    prompt_token_estimate INTEGER CHECK (prompt_token_estimate IS NULL OR prompt_token_estimate >= 0),
    locale TEXT,
    source_channel TEXT NOT NULL DEFAULT 'chat' CHECK (source_channel IN ('chat', 'upload', 'artifact', 'automation')),
    retrieval_used BOOLEAN NOT NULL DEFAULT false,
    retrieval_outcome TEXT,
    generation_outcome TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ae_prompt_events_user_time
    ON ae_prompt_events (tenant_id, user_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_prompt_events_hash
    ON ae_prompt_events (tenant_id, prompt_hash);

CREATE TABLE IF NOT EXISTS ae_prompt_intent_classifications (
    intent_classification_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_event_id UUID NOT NULL REFERENCES ae_prompt_events(prompt_event_id) ON DELETE CASCADE,
    intent_label TEXT NOT NULL,
    task_category TEXT NOT NULL,
    confidence NUMERIC(5,4) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    classifier_profile_id TEXT,
    prompt_template_version_id UUID REFERENCES ae_prompt_template_versions(prompt_template_version_id),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (prompt_event_id, intent_label, task_category)
);

CREATE TABLE IF NOT EXISTS ae_user_task_profiles (
    user_task_profile_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role_title TEXT,
    department TEXT,
    dominant_task_categories JSONB NOT NULL DEFAULT '[]'::jsonb,
    prompt_frequency JSONB NOT NULL DEFAULT '{}'::jsonb,
    automation_readiness_score NUMERIC(5,4) CHECK (automation_readiness_score IS NULL OR (automation_readiness_score >= 0 AND automation_readiness_score <= 1)),
    last_computed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, user_id)
);

CREATE TABLE IF NOT EXISTS ae_automation_recommendations (
    automation_recommendation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    source_prompt_event_id UUID REFERENCES ae_prompt_events(prompt_event_id) ON DELETE SET NULL,
    user_task_profile_id UUID REFERENCES ae_user_task_profiles(user_task_profile_id) ON DELETE SET NULL,
    recommendation_type TEXT NOT NULL CHECK (recommendation_type IN ('workflow', 'template', 'agent', 'integration')),
    title TEXT NOT NULL,
    rationale_summary TEXT NOT NULL CHECK (char_length(rationale_summary) <= 1000),
    confidence NUMERIC(5,4) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    status TEXT NOT NULL DEFAULT 'PROPOSED'
        CHECK (status IN ('PROPOSED', 'VIEWED', 'ACCEPTED', 'DISMISSED', 'EXPIRED')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ae_recommendations_user_status
    ON ae_automation_recommendations (tenant_id, user_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS ae_recommendation_feedback (
    recommendation_feedback_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    automation_recommendation_id UUID NOT NULL REFERENCES ae_automation_recommendations(automation_recommendation_id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    feedback_value TEXT NOT NULL CHECK (feedback_value IN ('helpful', 'not_helpful', 'accepted', 'dismissed')),
    feedback_reason TEXT CHECK (feedback_reason IS NULL OR char_length(feedback_reason) <= 1000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (version, description)
VALUES ('0021_prompt_analytics_foundation', 'AE chat, prompt registry, prompt analytics, and automation recommendation foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
