BEGIN;

CREATE TABLE IF NOT EXISTS service_worker_heartbeats (
    service_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    heartbeat_schema_version TEXT NOT NULL DEFAULT 'worker_heartbeat.v1'
        CHECK (heartbeat_schema_version = 'worker_heartbeat.v1'),
    worker_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('STARTING', 'IDLE', 'BUSY', 'STOPPING', 'STOPPED', 'ERROR')),
    active_job_id TEXT,
    trace_id TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (service_id, worker_id),
    CONSTRAINT ck_service_worker_heartbeats_busy_job CHECK (status <> 'BUSY' OR active_job_id IS NOT NULL),
    CONSTRAINT ck_service_worker_heartbeats_last_seen_order CHECK (last_seen_at >= started_at)
);

CREATE INDEX IF NOT EXISTS ix_service_worker_heartbeats_service_status
    ON service_worker_heartbeats (service_id, status);

CREATE INDEX IF NOT EXISTS ix_service_worker_heartbeats_type_status
    ON service_worker_heartbeats (worker_type, status);

CREATE INDEX IF NOT EXISTS ix_service_worker_heartbeats_last_seen
    ON service_worker_heartbeats (last_seen_at);

CREATE INDEX IF NOT EXISTS ix_service_worker_heartbeats_active_job
    ON service_worker_heartbeats (active_job_id);

INSERT INTO schema_migrations (version, description)
VALUES ('0112_service_worker_heartbeat_foundation', 'CX service worker heartbeat foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
