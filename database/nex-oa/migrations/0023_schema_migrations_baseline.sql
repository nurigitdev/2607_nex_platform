BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (version, description)
VALUES ('0023_schema_migrations_baseline', 'OA schema migration baseline')
ON CONFLICT (version) DO NOTHING;

COMMIT;
