BEGIN;

CREATE INDEX IF NOT EXISTS idx_ag_evt_retention_time
    ON service_operational_events (created_at ASC, event_id ASC);

CREATE INDEX IF NOT EXISTS idx_ag_exp_retention_time
    ON ag_ev_exports (updated_at ASC, export_id ASC);

INSERT INTO schema_migrations (version, description)
VALUES ('0887_ag_retention_candidate_indexes', 'AG retention candidate deterministic read indexes')
ON CONFLICT (version) DO NOTHING;

COMMIT;
