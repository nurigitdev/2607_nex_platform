BEGIN;

CREATE INDEX IF NOT EXISTS idx_ag_evt_type_page
    ON service_operational_events (event_type, created_at DESC, event_id DESC);

CREATE INDEX IF NOT EXISTS idx_ag_evt_trace_page
    ON service_operational_events (trace_id, created_at DESC, event_id DESC);

CREATE INDEX IF NOT EXISTS idx_ag_exp_trace_page
    ON ag_ev_exports (trace_id, updated_at DESC, export_id DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('0877_ag_resilience_read_indexes', 'AG resilience bounded-read indexes')
ON CONFLICT (version) DO NOTHING;

COMMIT;
