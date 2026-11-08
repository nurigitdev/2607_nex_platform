BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_conversations (
    conversation_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    workspace_id UUID NOT NULL REFERENCES ae_workspaces(workspace_id),
    owner_user_id TEXT NOT NULL,
    title TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    next_journal_seq BIGINT NOT NULL DEFAULT 1 CHECK (next_journal_seq >= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    CONSTRAINT ux_ae_conv_tenant UNIQUE (tenant_id, conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_ae_conv_workspace_time
    ON ae_conversations (tenant_id, owner_user_id, workspace_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS ae_conversation_messages (
    message_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    conversation_id UUID NOT NULL,
    journal_seq BIGINT NOT NULL CHECK (journal_seq >= 1),
    role TEXT NOT NULL CHECK (role IN ('USER', 'ASSISTANT', 'SYSTEM', 'TOOL')),
    content_ref TEXT NOT NULL CHECK (char_length(content_ref) > 0),
    content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    content_type TEXT NOT NULL CHECK (char_length(content_type) BETWEEN 1 AND 120),
    legacy_interaction_id UUID NULL,
    supersedes_message_id UUID NULL REFERENCES ae_conversation_messages(message_id),
    correlation_id TEXT NOT NULL,
    causation_id TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_ae_conv_msg_conversation
        FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES ae_conversations (tenant_id, conversation_id),
    CONSTRAINT ux_ae_conv_msg_seq UNIQUE (conversation_id, journal_seq)
);

CREATE INDEX IF NOT EXISTS idx_ae_conv_msg_lineage
    ON ae_conversation_messages (conversation_id, created_at, message_id);

CREATE TABLE IF NOT EXISTS ae_conversation_events (
    event_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    conversation_id UUID NOT NULL,
    journal_seq BIGINT NOT NULL CHECK (journal_seq >= 1),
    event_type TEXT NOT NULL CHECK (char_length(event_type) BETWEEN 1 AND 120),
    event_data JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(event_data) = 'object'),
    supersedes_event_id UUID NULL REFERENCES ae_conversation_events(event_id),
    correlation_id TEXT NOT NULL,
    causation_id TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_ae_conv_event_conversation
        FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES ae_conversations (tenant_id, conversation_id),
    CONSTRAINT ux_ae_conv_event_seq UNIQUE (conversation_id, journal_seq)
);

CREATE INDEX IF NOT EXISTS idx_ae_conv_event_lineage
    ON ae_conversation_events (conversation_id, created_at, event_id);

CREATE OR REPLACE FUNCTION reject_ae_conversation_journal_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'AE conversation journal rows are append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_ae_conv_msg_append_only ON ae_conversation_messages;
CREATE TRIGGER trg_ae_conv_msg_append_only
BEFORE UPDATE OR DELETE ON ae_conversation_messages
FOR EACH ROW EXECUTE FUNCTION reject_ae_conversation_journal_mutation();

DROP TRIGGER IF EXISTS trg_ae_conv_event_append_only ON ae_conversation_events;
CREATE TRIGGER trg_ae_conv_event_append_only
BEFORE UPDATE OR DELETE ON ae_conversation_events
FOR EACH ROW EXECUTE FUNCTION reject_ae_conversation_journal_mutation();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2002_ae_conversation_journal',
    'Project-neutral Conversation and append-only private-content journal'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
