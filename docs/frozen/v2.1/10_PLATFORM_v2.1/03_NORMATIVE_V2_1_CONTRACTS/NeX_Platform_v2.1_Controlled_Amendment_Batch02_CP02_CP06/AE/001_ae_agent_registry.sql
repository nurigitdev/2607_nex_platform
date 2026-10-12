-- NeX-AE Agent Registry v2.1 — E1 Contract Hardening
CREATE TABLE IF NOT EXISTS ae_agent_identity (
    tenant_id      text        NOT NULL,
    agent_id       text        NOT NULL,
    agent_type     text        NOT NULL CHECK (agent_type IN ('IA','CA','PA','EA')),
    profile_ref    text        NOT NULL,
    status         text        NOT NULL CHECK (status IN ('ACTIVE','SUSPENDED','RETIRED')),
    project_id     text        NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    version        bigint      NOT NULL DEFAULT 1,
    PRIMARY KEY (tenant_id, agent_id),
    CHECK (agent_type <> 'PA' OR project_id IS NOT NULL)
);

-- Exactly one ACTIVE Project Agent per tenant/project.
CREATE UNIQUE INDEX IF NOT EXISTS ux_ae_active_pa_per_project
ON ae_agent_identity (tenant_id, project_id)
WHERE agent_type = 'PA' AND status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS ix_ae_agent_identity_project
ON ae_agent_identity (tenant_id, project_id, agent_type);
