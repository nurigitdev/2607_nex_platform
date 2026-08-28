BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE ae_artifact_handoffs
    ADD COLUMN IF NOT EXISTS trace_id TEXT NOT NULL
        DEFAULT '00000000000000000000000000000000'
        CHECK (trace_id ~ '^[0-9a-f]{32}$');

ALTER TABLE ae_artifact_handoffs
    ADD COLUMN IF NOT EXISTS request_id TEXT NOT NULL
        DEFAULT 'migration-backfill';

ALTER TABLE ae_artifact_handoffs
    ALTER COLUMN trace_id DROP DEFAULT;

ALTER TABLE ae_artifact_handoffs
    ALTER COLUMN request_id DROP DEFAULT;

INSERT INTO schema_migrations (version, description)
VALUES (
    '0406_ae_artifact_handoff_trace_request_columns',
    'AE artifact handoff trace and request correlation columns'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
