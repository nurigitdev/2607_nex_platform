BEGIN;

ALTER TABLE service_jobs
    ADD COLUMN IF NOT EXISTS replay_lineage JSONB;

INSERT INTO schema_migrations (version, description)
VALUES ('0135_service_job_replay_lineage', 'MO service job replay lineage')
ON CONFLICT (version) DO NOTHING;

COMMIT;
