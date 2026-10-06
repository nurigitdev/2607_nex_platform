BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_oa_auth_events_trace
    ON oa_auth_events (trace_id, occurred_at ASC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '1376_oa_trace_projection_index',
    'OA authentication trace projection index'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
