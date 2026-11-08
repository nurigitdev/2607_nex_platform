BEGIN;

CREATE TABLE IF NOT EXISTS service_worker_heartbeats (
    service_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    heartbeat_schema_version TEXT NOT NULL DEFAULT 'worker_heartbeat.v1'
        CHECK (heartbeat_schema_version = 'worker_heartbeat.v1'),
    worker_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('STARTING', 'IDLE', 'BUSY', 'STOPPING', 'STOPPED', 'ERROR')
    ),
    active_job_id TEXT,
    trace_id TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (service_id, worker_id),
    CONSTRAINT ck_eos_worker_hb_busy_job
        CHECK (status <> 'BUSY' OR active_job_id IS NOT NULL),
    CONSTRAINT ck_eos_worker_hb_seen_order
        CHECK (last_seen_at >= started_at)
);

CREATE INDEX IF NOT EXISTS ix_eos_worker_hb_service_status
    ON service_worker_heartbeats (service_id, status);

CREATE INDEX IF NOT EXISTS ix_eos_worker_hb_last_seen
    ON service_worker_heartbeats (last_seen_at);

INSERT INTO schema_migrations (version, description)
VALUES ('2515_eos_worker_heartbeat', 'EOS Demo worker heartbeat foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
