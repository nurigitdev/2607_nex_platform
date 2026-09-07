BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_artifact_retention_scheduler_daemon_runs (
    daemon_run_record_id TEXT PRIMARY KEY,
    daemon_run_record_schema_version TEXT NOT NULL
        DEFAULT 'ae_artifact_retention_scheduler_daemon_run_record.v1'
        CHECK (
            daemon_run_record_schema_version =
            'ae_artifact_retention_scheduler_daemon_run_record.v1'
        ),
    service_id TEXT NOT NULL DEFAULT 'nex-ae-api'
        CHECK (service_id = 'nex-ae-api'),
    scheduler_id TEXT NOT NULL,
    daemon_instance_id TEXT NOT NULL,
    daemon_cli_execution_result_id TEXT NOT NULL UNIQUE,
    daemon_cli_execute_command_id TEXT NOT NULL,
    daemon_process_lock_id TEXT NOT NULL,
    started_daemon_run_id TEXT NOT NULL,
    completed_daemon_run_id TEXT NOT NULL,
    process_id INTEGER NOT NULL CHECK (process_id >= 1),
    host_id TEXT NOT NULL,
    run_status TEXT NOT NULL
        CHECK (run_status IN ('PENDING', 'RUNNING', 'STOPPING', 'SUCCEEDED', 'FAILED')),
    result_status TEXT NOT NULL
        CHECK (result_status IN ('SUCCEEDED', 'FAILED', 'STOPPED', 'SKIPPED')),
    stop_reason TEXT NOT NULL,
    max_cycles INTEGER NOT NULL CHECK (max_cycles >= 1 AND max_cycles <= 100),
    cycle_count INTEGER NOT NULL CHECK (cycle_count >= 0),
    worker_requested BOOLEAN NOT NULL,
    job_enqueued BOOLEAN NOT NULL,
    worker_executed BOOLEAN NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(summary) = 'object'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    execution_result_hash TEXT NOT NULL
        CHECK (execution_result_hash ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_ae_artifact_retention_scheduler_daemon_runs_cycle_count
        CHECK (cycle_count <= max_cycles),
    CONSTRAINT ck_ae_artifact_retention_scheduler_daemon_runs_completed_time
        CHECK (completed_at >= started_at)
);

CREATE TABLE IF NOT EXISTS ae_artifact_retention_scheduler_daemon_lifecycle_events (
    daemon_lifecycle_event_id TEXT PRIMARY KEY,
    daemon_lifecycle_event_schema_version TEXT NOT NULL
        DEFAULT 'ae_artifact_retention_scheduler_daemon_lifecycle_event.v1'
        CHECK (
            daemon_lifecycle_event_schema_version =
            'ae_artifact_retention_scheduler_daemon_lifecycle_event.v1'
        ),
    daemon_run_record_id TEXT NOT NULL
        REFERENCES ae_artifact_retention_scheduler_daemon_runs
        (daemon_run_record_id)
        ON DELETE CASCADE,
    daemon_cli_execution_result_id TEXT NOT NULL,
    daemon_run_metadata_id TEXT NOT NULL,
    service_id TEXT NOT NULL DEFAULT 'nex-ae-api'
        CHECK (service_id = 'nex-ae-api'),
    scheduler_id TEXT NOT NULL,
    daemon_instance_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('RUN_STARTED', 'RUN_COMPLETED')),
    run_status TEXT NOT NULL
        CHECK (run_status IN ('PENDING', 'RUNNING', 'STOPPING', 'SUCCEEDED', 'FAILED')),
    result_status TEXT CHECK (
        result_status IS NULL
        OR result_status IN ('SUCCEEDED', 'FAILED', 'STOPPED', 'SKIPPED')
    ),
    stop_reason TEXT,
    cycle_count INTEGER NOT NULL CHECK (cycle_count >= 0),
    occurred_at TIMESTAMPTZ NOT NULL,
    process_id INTEGER NOT NULL CHECK (process_id >= 1),
    host_id TEXT NOT NULL,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(summary) = 'object'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_ae_artifact_retention_scheduler_daemon_lifecycle_started
        CHECK (
            event_type <> 'RUN_STARTED'
            OR (
                run_status = 'RUNNING'
                AND result_status IS NULL
                AND stop_reason IS NULL
                AND cycle_count = 0
            )
        ),
    CONSTRAINT ck_ae_artifact_retention_scheduler_daemon_lifecycle_completed
        CHECK (
            event_type <> 'RUN_COMPLETED'
            OR (
                result_status IS NOT NULL
                AND stop_reason IS NOT NULL
            )
        )
);

CREATE INDEX IF NOT EXISTS
    idx_ae_artifact_retention_scheduler_daemon_runs_scheduler_completed
    ON ae_artifact_retention_scheduler_daemon_runs
    (scheduler_id, completed_at DESC);

CREATE INDEX IF NOT EXISTS
    idx_ae_artifact_retention_scheduler_daemon_runs_status_completed
    ON ae_artifact_retention_scheduler_daemon_runs
    (result_status, completed_at DESC);

CREATE INDEX IF NOT EXISTS
    idx_ae_artifact_retention_scheduler_daemon_lifecycle_events_run
    ON ae_artifact_retention_scheduler_daemon_lifecycle_events
    (daemon_run_record_id, occurred_at ASC);

CREATE INDEX IF NOT EXISTS
    idx_ae_artifact_retention_scheduler_daemon_lifecycle_events_scheduler
    ON ae_artifact_retention_scheduler_daemon_lifecycle_events
    (scheduler_id, occurred_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '0557_ae_artifact_retention_scheduler_daemon_run_persistence',
    'AE artifact retention scheduler daemon run and lifecycle event persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
