BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_project_lifecycle_inbox (
    tenant_id TEXT NOT NULL,
    event_id UUID NOT NULL,
    business_operation_id UUID NOT NULL,
    project_id UUID NOT NULL,
    project_code TEXT NOT NULL,
    project_state TEXT NOT NULL
        CHECK (project_state IN ('ACTIVE', 'INACTIVE', 'CLOSING', 'CLOSED')),
    project_version INTEGER NOT NULL CHECK (project_version >= 1),
    profile_policy_ref TEXT NOT NULL,
    event_payload_hash TEXT NOT NULL CHECK (char_length(event_payload_hash) = 71),
    event_payload JSONB NOT NULL,
    agent_id UUID NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, event_id),
    CONSTRAINT ux_ae_project_lifecycle_version
        UNIQUE (tenant_id, project_id, project_version)
);

CREATE INDEX IF NOT EXISTS ix_ae_project_lifecycle_project
    ON ae_project_lifecycle_inbox (tenant_id, project_id, project_version DESC);

CREATE TABLE IF NOT EXISTS ae_project_agent_sync (
    tenant_id TEXT NOT NULL,
    project_id UUID NOT NULL,
    project_code TEXT NOT NULL,
    project_state TEXT NOT NULL
        CHECK (project_state IN ('ACTIVE', 'INACTIVE', 'CLOSING', 'CLOSED')),
    project_version INTEGER NOT NULL CHECK (project_version >= 1),
    profile_policy_ref TEXT NOT NULL,
    profile_policy_hash TEXT NOT NULL CHECK (char_length(profile_policy_hash) = 71),
    agent_id UUID NOT NULL,
    agent_status TEXT NOT NULL
        CHECK (agent_status IN ('ACTIVE', 'SUSPENDED', 'RETIRED')),
    capability_mode TEXT NOT NULL
        CHECK (capability_mode IN ('ORDINARY', 'SUSPENDED', 'CLOSURE', 'RETIRED')),
    last_event_id UUID NOT NULL,
    last_event_payload_hash TEXT NOT NULL
        CHECK (char_length(last_event_payload_hash) = 71),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, project_id),
    CONSTRAINT ux_ae_project_agent_sync_agent UNIQUE (tenant_id, agent_id),
    CONSTRAINT fk_ae_project_agent_sync_identity
        FOREIGN KEY (tenant_id, agent_id)
        REFERENCES ae_agent_identity (tenant_id, agent_id)
);

CREATE INDEX IF NOT EXISTS ix_ae_project_agent_sync_state
    ON ae_project_agent_sync (tenant_id, project_state, agent_status);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2515_ae_project_agent_lifecycle',
    'Idempotent EOS Project lifecycle inbox and AE Project Agent synchronization'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
