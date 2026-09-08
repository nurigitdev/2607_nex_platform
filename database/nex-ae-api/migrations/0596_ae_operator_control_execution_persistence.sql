BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_daemon_operator_control_execution_states (
    operator_control_execution_state_id TEXT PRIMARY KEY,
    operator_control_execution_state_schema_version TEXT NOT NULL
        DEFAULT 'ae_artifact_retention_scheduler_daemon_operator_control_execution_state.v1'
        CHECK (
            operator_control_execution_state_schema_version =
            'ae_artifact_retention_scheduler_daemon_operator_control_execution_state.v1'
        ),
    service_id TEXT NOT NULL DEFAULT 'nex-ae-api'
        CHECK (service_id = 'nex-ae-api'),
    scheduler_id TEXT NOT NULL,
    operator_control_execution_request_id TEXT NOT NULL,
    operator_control_facade_id TEXT NOT NULL,
    operator_control_request_id TEXT NOT NULL,
    operator_control_admission_id TEXT NOT NULL,
    operator_control_command_preview_id TEXT NOT NULL,
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
    execution_status TEXT NOT NULL
        CHECK (
            execution_status IN (
                'ADMITTED',
                'EXECUTING',
                'SUCCEEDED',
                'FAILED',
                'BLOCKED',
                'NOOP'
            )
        ),
    idempotency_key TEXT NOT NULL,
    idempotency_status TEXT NOT NULL
        CHECK (idempotency_status IN ('NEW', 'REPLAYED', 'CONFLICT')),
    decision_reason TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    prior_execution_state_id TEXT,
    operator_control_execution_request_hash TEXT NOT NULL
        CHECK (operator_control_execution_request_hash ~ '^[0-9a-f]{64}$'),
    allowed_next_statuses JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(allowed_next_statuses) = 'array'),
    guardrails JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(guardrails) = 'object'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    operator_control_execution_request JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(operator_control_execution_request) = 'object'),
    execution_state_hash TEXT NOT NULL
        CHECK (execution_state_hash ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_daemon_operator_control_execution_transitions (
    operator_control_execution_state_transition_id TEXT PRIMARY KEY,
    operator_control_execution_state_transition_schema_version TEXT NOT NULL
        DEFAULT 'ae_artifact_retention_scheduler_daemon_operator_control_execution_state_transition.v1'
        CHECK (
            operator_control_execution_state_transition_schema_version =
            'ae_artifact_retention_scheduler_daemon_operator_control_execution_state_transition.v1'
        ),
    service_id TEXT NOT NULL DEFAULT 'nex-ae-api'
        CHECK (service_id = 'nex-ae-api'),
    scheduler_id TEXT NOT NULL,
    operator_control_execution_state_id TEXT NOT NULL
        REFERENCES ae_daemon_operator_control_execution_states
        (operator_control_execution_state_id)
        ON DELETE CASCADE,
    operator_control_execution_request_id TEXT NOT NULL,
    from_status TEXT NOT NULL
        CHECK (
            from_status IN (
                'ADMITTED',
                'EXECUTING',
                'SUCCEEDED',
                'FAILED',
                'BLOCKED',
                'NOOP'
            )
        ),
    to_status TEXT NOT NULL
        CHECK (
            to_status IN (
                'ADMITTED',
                'EXECUTING',
                'SUCCEEDED',
                'FAILED',
                'BLOCKED',
                'NOOP'
            )
        ),
    decision_reason TEXT NOT NULL,
    transitioned_at TIMESTAMPTZ NOT NULL,
    operator_control_execution_state JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(operator_control_execution_state) = 'object'),
    guardrails JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(guardrails) = 'object'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    transition_hash TEXT NOT NULL
        CHECK (transition_hash ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ae_operator_control_execution_states_observed
    ON ae_daemon_operator_control_execution_states
    (scheduler_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_operator_control_execution_states_status
    ON ae_daemon_operator_control_execution_states
    (execution_status, idempotency_status, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_operator_control_execution_states_idempotency
    ON ae_daemon_operator_control_execution_states
    (idempotency_key, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_operator_control_execution_states_request
    ON ae_daemon_operator_control_execution_states
    (operator_control_execution_request_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_operator_control_execution_transitions_state
    ON ae_daemon_operator_control_execution_transitions
    (operator_control_execution_state_id, transitioned_at ASC);

CREATE INDEX IF NOT EXISTS idx_ae_operator_control_execution_transitions_scheduler
    ON ae_daemon_operator_control_execution_transitions
    (scheduler_id, transitioned_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '0596_ae_operator_control_execution_persistence',
    'AE artifact retention scheduler daemon operator-control execution state and transition persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
