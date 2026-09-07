BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_artifact_retention_scheduler_daemon_supervisor_results (
    daemon_supervisor_record_id TEXT PRIMARY KEY,
    daemon_supervisor_record_schema_version TEXT NOT NULL
        DEFAULT 'ae_artifact_retention_scheduler_daemon_supervisor_record.v1'
        CHECK (
            daemon_supervisor_record_schema_version =
            'ae_artifact_retention_scheduler_daemon_supervisor_record.v1'
        ),
    service_id TEXT NOT NULL DEFAULT 'nex-ae-api'
        CHECK (service_id = 'nex-ae-api'),
    scheduler_id TEXT NOT NULL,
    daemon_supervisor_command_id TEXT NOT NULL,
    daemon_supervisor_result_id TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL
        CHECK (action IN ('status_probe', 'start_daemon', 'stop_daemon')),
    result_status TEXT NOT NULL
        CHECK (result_status IN ('READY', 'BLOCKED', 'NOOP', 'FAILED')),
    decision_reason TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL,
    runtime_ready BOOLEAN NOT NULL,
    supervisor_adapter_available BOOLEAN NOT NULL,
    supervisor_adapter_invoked BOOLEAN NOT NULL,
    adapter_name TEXT,
    process_started BOOLEAN NOT NULL DEFAULT false
        CHECK (process_started = false),
    process_stopped BOOLEAN NOT NULL DEFAULT false
        CHECK (process_stopped = false),
    message TEXT,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(summary) = 'object'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    supervisor_command JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(supervisor_command) = 'object'),
    supervisor_result JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(supervisor_result) = 'object'),
    supervisor_result_hash TEXT NOT NULL
        CHECK (supervisor_result_hash ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_ae_artifact_retention_scheduler_daemon_supervisor_adapter_name
        CHECK (
            (
                supervisor_adapter_available = true
                AND adapter_name IS NOT NULL
            )
            OR (
                supervisor_adapter_available = false
                AND adapter_name IS NULL
            )
        )
);

CREATE TABLE IF NOT EXISTS ae_artifact_retention_scheduler_daemon_supervisor_events (
    daemon_supervisor_event_id TEXT PRIMARY KEY,
    daemon_supervisor_event_schema_version TEXT NOT NULL
        DEFAULT 'ae_artifact_retention_scheduler_daemon_supervisor_event.v1'
        CHECK (
            daemon_supervisor_event_schema_version =
            'ae_artifact_retention_scheduler_daemon_supervisor_event.v1'
        ),
    daemon_supervisor_record_id TEXT NOT NULL
        REFERENCES ae_artifact_retention_scheduler_daemon_supervisor_results
        (daemon_supervisor_record_id)
        ON DELETE CASCADE,
    daemon_supervisor_command_id TEXT NOT NULL,
    daemon_supervisor_result_id TEXT NOT NULL,
    service_id TEXT NOT NULL DEFAULT 'nex-ae-api'
        CHECK (service_id = 'nex-ae-api'),
    scheduler_id TEXT NOT NULL,
    action TEXT NOT NULL
        CHECK (action IN ('status_probe', 'start_daemon', 'stop_daemon')),
    result_status TEXT NOT NULL
        CHECK (result_status IN ('READY', 'BLOCKED', 'NOOP', 'FAILED')),
    decision_reason TEXT NOT NULL,
    event_type TEXT NOT NULL
        CHECK (event_type = 'SUPERVISOR_RESULT_RECORDED'),
    occurred_at TIMESTAMPTZ NOT NULL,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(summary) = 'object'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS
    idx_ae_artifact_retention_scheduler_daemon_supervisor_results_observed
    ON ae_artifact_retention_scheduler_daemon_supervisor_results
    (scheduler_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS
    idx_ae_artifact_retention_scheduler_daemon_supervisor_results_action
    ON ae_artifact_retention_scheduler_daemon_supervisor_results
    (action, result_status, observed_at DESC);

CREATE INDEX IF NOT EXISTS
    idx_ae_artifact_retention_scheduler_daemon_supervisor_events_record
    ON ae_artifact_retention_scheduler_daemon_supervisor_events
    (daemon_supervisor_record_id, occurred_at ASC);

CREATE INDEX IF NOT EXISTS
    idx_ae_artifact_retention_scheduler_daemon_supervisor_events_scheduler
    ON ae_artifact_retention_scheduler_daemon_supervisor_events
    (scheduler_id, occurred_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '0564_ae_artifact_retention_scheduler_daemon_supervisor_persistence',
    'AE artifact retention scheduler daemon supervisor result and event persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
