-- NeX-AE RuntimeJob / JobQueue v2.1
CREATE TABLE IF NOT EXISTS ae_runtime_job (
    tenant_id              text        NOT NULL,
    runtime_job_id         text        NOT NULL,
    job_type               text        NOT NULL,
    execution_id           text        NOT NULL,
    executable_step_id     text        NULL,
    wait_id                text        NULL,
    reconciliation_id      text        NULL,
    result_delivery_id      text        NULL,
    publication_reconciliation_id text   NULL,
    state                  text        NOT NULL,
    dedup_key              text        NOT NULL,
    attempt_no             integer     NOT NULL DEFAULT 0,
    run_after              timestamptz NOT NULL,
    lease_owner            text        NULL,
    lease_token            text        NULL,
    lease_until            timestamptz NULL,
    payload_json           jsonb       NOT NULL DEFAULT '{}'::jsonb,
    correlation_id         text        NOT NULL,
    causation_id           text        NULL,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, runtime_job_id),
    UNIQUE (tenant_id, dedup_key)
);

CREATE INDEX IF NOT EXISTS ix_ae_runtime_job_runnable
ON ae_runtime_job (run_after, state)
WHERE state = 'QUEUED';

CREATE TABLE IF NOT EXISTS ae_runtime_job_attempt (
    attempt_id             text        PRIMARY KEY,
    tenant_id              text        NOT NULL,
    runtime_job_id         text        NOT NULL,
    attempt_no             integer     NOT NULL,
    worker_id              text        NOT NULL,
    lease_token            text        NOT NULL,
    started_at             timestamptz NOT NULL,
    ended_at               timestamptz NULL,
    outcome                text        NOT NULL,
    error_ref              text        NULL,
    retry_disposition_ref  text        NULL,
    UNIQUE (tenant_id, runtime_job_id, attempt_no)
);
