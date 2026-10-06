BEGIN;

CREATE INDEX IF NOT EXISTS ix_cx_ingest_runs_trace
    ON cx_ingest_runs (trace_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_cx_gen_exec_trace
    ON cx_generation_executions (trace_id, updated_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '1374_cx_trace_projection_indexes',
    'CX ingestion and generation trace projection lookup indexes'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
