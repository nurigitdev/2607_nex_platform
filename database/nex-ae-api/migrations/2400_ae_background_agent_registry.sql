BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ae_active_pa_project
    ON ae_agent_identity (tenant_id, project_id)
    WHERE agent_type = 'PA' AND status = 'ACTIVE';

INSERT INTO schema_migrations (version, description)
VALUES ('2400_ae_background_agent_registry', 'AE CA PA EA registry and active PA uniqueness')
ON CONFLICT (version) DO NOTHING;

COMMIT;
