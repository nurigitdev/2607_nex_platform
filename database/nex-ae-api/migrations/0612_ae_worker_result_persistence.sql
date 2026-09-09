BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_op_exec_worker_results (
    operator_control_execution_worker_result_id TEXT PRIMARY KEY,
    operator_control_execution_worker_result_record_schema_version TEXT NOT NULL
        DEFAULT 'ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record.v1'
        CHECK (
            operator_control_execution_worker_result_record_schema_version =
            'ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record.v1'
        ),
    service_id TEXT NOT NULL DEFAULT 'nex-ae-api'
        CHECK (service_id = 'nex-ae-api'),
    scheduler_id TEXT NOT NULL,
    operator_control_execution_worker_command_id TEXT NOT NULL,
    operator_control_execution_worker_plan_id TEXT NOT NULL,
    operator_control_execution_worker_transition_plan_id TEXT NOT NULL,
    operator_control_execution_state_id TEXT NOT NULL
        REFERENCES ae_daemon_operator_control_execution_states
        (operator_control_execution_state_id)
        ON DELETE CASCADE,
    operator_control_execution_request_id TEXT NOT NULL,
    action TEXT NOT NULL
        CHECK (
            action IN (
                'status_probe',
                'start_daemon',
                'stop_daemon',
                'restart_daemon'
            )
        ),
    execution_mode TEXT NOT NULL
        CHECK (
            execution_mode IN (
                'contract_only',
                'fake_dry_run_supervisor_persistent_dispatch'
            )
        ),
    worker_mode TEXT NOT NULL,
    worker_status TEXT NOT NULL
        CHECK (worker_status IN ('SUCCEEDED', 'FAILED', 'BLOCKED')),
    decision_reason TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    transition_plan_status TEXT NOT NULL
        CHECK (transition_plan_status IN ('READY', 'BLOCKED')),
    transition_terminal_status TEXT NOT NULL
        CHECK (transition_terminal_status IN ('SUCCEEDED', 'FAILED', 'BLOCKED')),
    status_path JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(status_path) = 'array'),
    supervisor_result_count INTEGER NOT NULL
        CHECK (supervisor_result_count >= 0 AND supervisor_result_count <= 2),
    supervisor_result_statuses JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(supervisor_result_statuses) = 'array'),
    supervisor_actions JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(supervisor_actions) = 'array'),
    supervisor_result_ids JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(supervisor_result_ids) = 'array'),
    supervisor_dispatch_performed BOOLEAN NOT NULL,
    supervisor_adapter_invoked BOOLEAN NOT NULL,
    subprocess_started BOOLEAN NOT NULL,
    subprocess_stopped BOOLEAN NOT NULL,
    worker_execution_performed BOOLEAN NOT NULL,
    transition_persistence_performed BOOLEAN NOT NULL,
    physical_delete_automation_enabled BOOLEAN NOT NULL,
    operator_control_execution_worker_command_hash TEXT NOT NULL
        CHECK (operator_control_execution_worker_command_hash ~ '^[0-9a-f]{64}$'),
    operator_control_execution_worker_transition_plan_hash TEXT NOT NULL
        CHECK (
            operator_control_execution_worker_transition_plan_hash ~
            '^[0-9a-f]{64}$'
        ),
    supervisor_results_hash TEXT NOT NULL
        CHECK (supervisor_results_hash ~ '^[0-9a-f]{64}$'),
    worker_result_hash TEXT NOT NULL
        CHECK (worker_result_hash ~ '^[0-9a-f]{64}$'),
    guardrails JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(guardrails) = 'object'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ae_op_worker_results_observed
    ON ae_op_exec_worker_results
    (scheduler_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_op_worker_results_state
    ON ae_op_exec_worker_results
    (operator_control_execution_state_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_op_worker_results_status
    ON ae_op_exec_worker_results
    (worker_status, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_op_worker_results_request
    ON ae_op_exec_worker_results
    (operator_control_execution_request_id, observed_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '0612_ae_worker_result_persistence',
    'AE operator-control execution worker result safe summary persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
