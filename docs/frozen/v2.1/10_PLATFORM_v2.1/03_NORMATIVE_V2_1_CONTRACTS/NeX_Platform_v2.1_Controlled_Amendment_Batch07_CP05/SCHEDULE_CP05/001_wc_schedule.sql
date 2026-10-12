-- NeX-WC Recurring Work / Schedule v1.1 — E2E-12 hardening
-- WC is the Business Schedule SoR. Runtime JobQueue timing is not Schedule SoR.
CREATE TABLE wc_schedule_spec (
    tenant_id                text        NOT NULL,
    schedule_id              text        NOT NULL,
    owner_ref                text        NOT NULL,
    project_id               text        NULL,
    timezone                 text        NOT NULL,
    time_semantics_version   text        NOT NULL DEFAULT 'WC_SCHEDULE_TIME_V1',
    nominal_time_basis       text        NOT NULL DEFAULT 'UTC_INSTANT',
    dst_gap_policy           text        NOT NULL DEFAULT 'SKIP_NONEXISTENT_LOCAL_TIME',
    dst_overlap_policy       text        NOT NULL DEFAULT 'EARLIEST_OFFSET_ONLY',
    schedule_expression_type text        NOT NULL,
    schedule_expression_profile text     NOT NULL,
    schedule_expression      text        NOT NULL,
    enabled                  boolean     NOT NULL DEFAULT true,
    misfire_policy           text        NOT NULL,
    max_catch_up             integer     NOT NULL DEFAULT 1,
    concurrency_policy       text        NOT NULL,
    target_json              jsonb       NOT NULL,
    last_run_at              timestamptz NULL,
    next_run_at              timestamptz NOT NULL,
    version                  bigint      NOT NULL DEFAULT 1,
    lease_owner              text        NULL,
    lease_until              timestamptz NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, schedule_id),
    CHECK (time_semantics_version = 'WC_SCHEDULE_TIME_V1'),
    CHECK (nominal_time_basis = 'UTC_INSTANT'),
    CHECK (schedule_expression_type IN ('CRON','FIXED_INTERVAL')),
    CHECK (schedule_expression_profile IN ('CRON5_V1','ISO8601_INTERVAL_V1')),
    CHECK (misfire_policy IN ('SKIP','CATCH_UP','LATEST_ONLY')),
    CHECK (concurrency_policy IN ('ALLOW_OVERLAP','FORBID_OVERLAP')),
    CHECK (max_catch_up BETWEEN 0 AND 100)
);

CREATE INDEX ix_wc_schedule_due
ON wc_schedule_spec (next_run_at)
WHERE enabled = true;

CREATE TABLE wc_schedule_occurrence (
    tenant_id                  text        NOT NULL,
    occurrence_id              text        NOT NULL,
    schedule_id                text        NOT NULL,
    schedule_version           bigint      NOT NULL,
    nominal_time               timestamptz NOT NULL,
    actual_evaluated_at        timestamptz NULL,
    state                      text        NOT NULL,
    materialization_key        text        NOT NULL,
    materialized_work_item_ref text        NULL,
    skip_reason                text        NULL,
    failure_ref                text        NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, occurrence_id),
    UNIQUE (tenant_id, schedule_id, nominal_time),
    UNIQUE (tenant_id, materialization_key),
    CHECK (state IN ('DUE','MATERIALIZING','MATERIALIZED','SKIPPED','FAILED'))
);

-- One occurrence has one semantic WorkItem materialization identity.
-- Same occurrence + same payload hash returns the existing WorkItem.
-- Same occurrence/materialization key + different payload hash is MATERIALIZATION_CONFLICT.
CREATE TABLE wc_schedule_materialization (
    tenant_id                 text        NOT NULL,
    occurrence_id             text        NOT NULL,
    schedule_id               text        NOT NULL,
    schedule_version          bigint      NOT NULL,
    materialization_key       text        NOT NULL,
    work_item_payload_hash    text        NOT NULL,
    work_item_id              text        NOT NULL,
    state                     text        NOT NULL DEFAULT 'COMMITTED',
    created_at                timestamptz NOT NULL DEFAULT now(),
    completed_at              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, occurrence_id),
    UNIQUE (tenant_id, materialization_key),
    UNIQUE (tenant_id, work_item_id),
    CHECK (state IN ('COMMITTED'))
);

CREATE TABLE wc_schedule_audit (
    audit_event_id             text        PRIMARY KEY,
    tenant_id                  text        NOT NULL,
    action                     text        NOT NULL,
    actor_type                 text        NOT NULL,
    actor_ref                  text        NOT NULL,
    authorization_decision_ref text        NOT NULL,
    correlation_id             text        NOT NULL,
    schedule_id                text        NOT NULL,
    schedule_version           bigint      NULL,
    occurrence_id              text        NULL,
    work_item_id               text        NULL,
    project_id                 text        NULL,
    outcome                    text        NULL,
    occurred_at                timestamptz NOT NULL,
    CHECK (action IN ('CREATE','UPDATE','ENABLE','DISABLE','GET','LIST','MATERIALIZE','SKIP','MATERIALIZATION_FAILED')),
    CHECK (actor_type IN ('HUMAN','AGENT','SERVICE_ACCOUNT'))
);
