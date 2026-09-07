BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_artifact_retention_scheduler_daemon_process_snapshots (
    daemon_supervised_process_record_id TEXT PRIMARY KEY,
    daemon_supervised_process_record_schema_version TEXT NOT NULL
        DEFAULT 'ae_artifact_retention_scheduler_daemon_supervised_process_record.v1'
        CHECK (
            daemon_supervised_process_record_schema_version =
            'ae_artifact_retention_scheduler_daemon_supervised_process_record.v1'
        ),
    service_id TEXT NOT NULL DEFAULT 'nex-ae-api'
        CHECK (service_id = 'nex-ae-api'),
    scheduler_id TEXT NOT NULL,
    daemon_supervisor_command_id TEXT NOT NULL,
    daemon_supervised_process_id TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL
        CHECK (action IN ('status_probe', 'start_daemon', 'stop_daemon')),
    process_status TEXT NOT NULL
        CHECK (
            process_status IN (
                'MISSING',
                'START_REQUESTED',
                'RUNNING',
                'STOP_REQUESTED',
                'STOPPED',
                'EXITED',
                'STALE',
                'FAILED',
                'BLOCKED'
            )
        ),
    process_mode TEXT NOT NULL,
    process_id INTEGER,
    host_id TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    exit_code INTEGER,
    termination_signal TEXT,
    process_running BOOLEAN NOT NULL,
    process_started_observed BOOLEAN NOT NULL,
    process_stopped_observed BOOLEAN NOT NULL,
    subprocess_adapter_required BOOLEAN NOT NULL,
    message TEXT,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(summary) = 'object'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    supervised_process_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(supervised_process_snapshot) = 'object'),
    supervised_process_snapshot_hash TEXT NOT NULL
        CHECK (supervised_process_snapshot_hash ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_artifact_retention_scheduler_daemon_process_events (
    daemon_supervised_process_event_id TEXT PRIMARY KEY,
    daemon_supervised_process_event_schema_version TEXT NOT NULL
        DEFAULT 'ae_artifact_retention_scheduler_daemon_supervised_process_event.v1'
        CHECK (
            daemon_supervised_process_event_schema_version =
            'ae_artifact_retention_scheduler_daemon_supervised_process_event.v1'
        ),
    daemon_supervised_process_record_id TEXT NOT NULL
        REFERENCES ae_artifact_retention_scheduler_daemon_process_snapshots
        (daemon_supervised_process_record_id)
        ON DELETE CASCADE,
    daemon_supervised_process_id TEXT NOT NULL,
    daemon_supervisor_command_id TEXT NOT NULL,
    service_id TEXT NOT NULL DEFAULT 'nex-ae-api'
        CHECK (service_id = 'nex-ae-api'),
    scheduler_id TEXT NOT NULL,
    action TEXT NOT NULL
        CHECK (action IN ('status_probe', 'start_daemon', 'stop_daemon')),
    process_status TEXT NOT NULL
        CHECK (
            process_status IN (
                'MISSING',
                'START_REQUESTED',
                'RUNNING',
                'STOP_REQUESTED',
                'STOPPED',
                'EXITED',
                'STALE',
                'FAILED',
                'BLOCKED'
            )
        ),
    event_type TEXT NOT NULL
        CHECK (event_type = 'SUPERVISED_PROCESS_SNAPSHOT_RECORDED'),
    occurred_at TIMESTAMPTZ NOT NULL,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(summary) = 'object'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ae_daemon_process_snapshots_observed
    ON ae_artifact_retention_scheduler_daemon_process_snapshots
    (scheduler_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_daemon_process_snapshots_action_status
    ON ae_artifact_retention_scheduler_daemon_process_snapshots
    (action, process_status, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_daemon_process_snapshots_pid
    ON ae_artifact_retention_scheduler_daemon_process_snapshots
    (host_id, process_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_daemon_process_events_record
    ON ae_artifact_retention_scheduler_daemon_process_events
    (daemon_supervised_process_record_id, occurred_at ASC);

CREATE INDEX IF NOT EXISTS idx_ae_daemon_process_events_scheduler
    ON ae_artifact_retention_scheduler_daemon_process_events
    (scheduler_id, occurred_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '0575_ae_artifact_retention_scheduler_daemon_supervised_process_persistence',
    'AE artifact retention scheduler daemon supervised process snapshot and event persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
