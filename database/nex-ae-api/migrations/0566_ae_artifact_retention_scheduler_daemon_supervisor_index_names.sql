BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ae_daemon_supervisor_results_observed
    ON ae_artifact_retention_scheduler_daemon_supervisor_results
    (scheduler_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_daemon_supervisor_results_action
    ON ae_artifact_retention_scheduler_daemon_supervisor_results
    (action, result_status, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_daemon_supervisor_events_record
    ON ae_artifact_retention_scheduler_daemon_supervisor_events
    (daemon_supervisor_record_id, occurred_at ASC);

CREATE INDEX IF NOT EXISTS idx_ae_daemon_supervisor_events_scheduler
    ON ae_artifact_retention_scheduler_daemon_supervisor_events
    (scheduler_id, occurred_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '0566_ae_artifact_retention_scheduler_daemon_supervisor_index_names',
    'AE daemon supervisor short canonical index names for PostgreSQL smoke checks'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
