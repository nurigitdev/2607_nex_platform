BEGIN;

ALTER TABLE wc_assignment
    ADD COLUMN IF NOT EXISTS agent_execution_id TEXT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_wc_assignment_execution
    ON wc_assignment (tenant_id, agent_execution_id)
    WHERE agent_execution_id IS NOT NULL;

INSERT INTO schema_migrations (version, description)
VALUES (
    '1005_wc_assignment_execution',
    'WC assignment acknowledgement of AE AgentExecution lineage'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
