BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_workspaces (
    workspace_id UUID PRIMARY KEY,
    workspace_schema_version TEXT NOT NULL DEFAULT 'ae_workspace_state.v1'
        CHECK (workspace_schema_version = 'ae_workspace_state.v1'),
    tenant_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    title TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
    locale TEXT NOT NULL CHECK (char_length(locale) BETWEEN 1 AND 32),
    chat_document_id UUID NOT NULL,
    runtime_defaults JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(runtime_defaults) = 'object'),
    activity_count INTEGER NOT NULL DEFAULT 0 CHECK (activity_count >= 0),
    last_activity_type TEXT NULL,
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ux_ae_ws_chat UNIQUE (chat_document_id)
);

CREATE INDEX IF NOT EXISTS idx_ae_ws_owner_time
    ON ae_workspaces (tenant_id, owner_user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS ae_workspace_activities (
    activity_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES ae_workspaces(workspace_id)
        ON DELETE CASCADE,
    activity_schema_version TEXT NOT NULL DEFAULT 'ae_workspace_activity.v1'
        CHECK (activity_schema_version = 'ae_workspace_activity.v1'),
    activity_type TEXT NOT NULL CHECK (char_length(activity_type) <= 120),
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    summary TEXT NOT NULL CHECK (char_length(summary) <= 512),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ae_ws_act_time
    ON ae_workspace_activities (workspace_id, created_at ASC, activity_id ASC);

ALTER TABLE ae_chat_interactions
    ADD COLUMN IF NOT EXISTS workspace_id UUID NULL
        REFERENCES ae_workspaces(workspace_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_ae_chat_ws_owner_time
    ON ae_chat_interactions
    (workspace_id, tenant_id, user_id, created_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '1014_ae_workspace_activity_persistence',
    'AE durable workspace, activity, and chat workspace linkage'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
