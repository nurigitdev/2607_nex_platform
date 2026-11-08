BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_rt_dispatch_lease (
    queue_name TEXT PRIMARY KEY CHECK (char_length(queue_name) > 0),
    owner_id TEXT NOT NULL CHECK (char_length(owner_id) > 0),
    fencing_token BIGINT NOT NULL CHECK (fencing_token >= 1),
    acquired_at TIMESTAMPTZ NOT NULL,
    renewed_at TIMESTAMPTZ NOT NULL,
    lease_until TIMESTAMPTZ NOT NULL,
    released_at TIMESTAMPTZ NULL,
    CHECK (lease_until > renewed_at),
    CHECK (renewed_at >= acquired_at),
    CHECK (released_at IS NULL OR released_at >= acquired_at)
);

CREATE INDEX IF NOT EXISTS idx_ae_rt_dispatch_expiry
    ON ae_rt_dispatch_lease (lease_until);

CREATE TABLE IF NOT EXISTS ae_rt_job_issue (
    issue_id TEXT PRIMARY KEY CHECK (char_length(issue_id) > 0),
    tenant_id TEXT NOT NULL,
    runtime_job_id TEXT NOT NULL,
    reason_code TEXT NOT NULL CHECK (reason_code IN (
        'STEP_ID_MISSING',
        'STEP_NOT_FOUND',
        'EXECUTOR_KIND_MISSING',
        'EXECUTOR_UNSUPPORTED'
    )),
    observed_executor_kind TEXT NULL,
    issue_state TEXT NOT NULL DEFAULT 'OPEN' CHECK (issue_state IN (
        'OPEN', 'ACKNOWLEDGED'
    )),
    detected_at TIMESTAMPTZ NOT NULL,
    acknowledged_at TIMESTAMPTZ NULL,
    CONSTRAINT fk_ae_rt_job_issue_job
        FOREIGN KEY (tenant_id, runtime_job_id)
        REFERENCES ae_runtime_job (tenant_id, runtime_job_id),
    CONSTRAINT ux_ae_rt_job_issue_job
        UNIQUE (tenant_id, runtime_job_id),
    CHECK (
        (issue_state = 'OPEN' AND acknowledged_at IS NULL)
        OR (issue_state = 'ACKNOWLEDGED' AND acknowledged_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_ae_rt_job_issue_state
    ON ae_rt_job_issue (issue_state, reason_code, detected_at);

CREATE INDEX IF NOT EXISTS idx_ae_rt_job_runnable
    ON ae_runtime_job (state, run_after, tenant_id, created_at, runtime_job_id)
    WHERE state = 'QUEUED';

CREATE INDEX IF NOT EXISTS idx_ae_rt_job_expired
    ON ae_runtime_job (state, lease_until, tenant_id, runtime_job_id)
    WHERE state = 'RUNNING';

CREATE INDEX IF NOT EXISTS idx_ae_step_executor
    ON ae_executable_step (tenant_id, executable_step_id, executor_kind)
    WHERE executor_kind IS NOT NULL;

INSERT INTO schema_migrations (version, description)
VALUES (
    '2200_ae_runtime_dispatch',
    'P6 capability-aware RuntimeJob dispatch leadership and issue foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
