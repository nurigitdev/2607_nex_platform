BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_agent_identity (
    tenant_id TEXT NOT NULL,
    agent_id UUID NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '2.1'
        CHECK (schema_version = '2.1'),
    agent_type TEXT NOT NULL
        CHECK (agent_type IN ('IA', 'CA', 'PA', 'EA')),
    profile_ref TEXT NOT NULL CHECK (char_length(profile_ref) > 0),
    status TEXT NOT NULL
        CHECK (status IN ('ACTIVE', 'SUSPENDED', 'RETIRED')),
    project_id TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    PRIMARY KEY (tenant_id, agent_id),
    CONSTRAINT ck_ae_agent_project_scope CHECK (
        (agent_type = 'PA' AND project_id IS NOT NULL AND char_length(project_id) > 0)
        OR (agent_type = 'IA' AND project_id IS NULL)
        OR agent_type IN ('CA', 'EA')
    )
);

CREATE INDEX IF NOT EXISTS idx_ae_agent_type_status
    ON ae_agent_identity (tenant_id, agent_type, status);

CREATE TABLE IF NOT EXISTS ae_ia_principal_assignment (
    assignment_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    principal_id TEXT NOT NULL CHECK (char_length(principal_id) > 0),
    agent_id UUID NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'REVOKED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    CONSTRAINT fk_ae_ia_assignment_agent
        FOREIGN KEY (tenant_id, agent_id)
        REFERENCES ae_agent_identity (tenant_id, agent_id),
    CONSTRAINT ux_ae_ia_assignment_principal UNIQUE (tenant_id, principal_id),
    CONSTRAINT ux_ae_ia_assignment_agent UNIQUE (tenant_id, agent_id)
);

CREATE INDEX IF NOT EXISTS idx_ae_ia_assignment_status
    ON ae_ia_principal_assignment (tenant_id, status);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2001_ae_agent_identity',
    'Canonical AgentIdentity and principal-to-IA assignment'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
