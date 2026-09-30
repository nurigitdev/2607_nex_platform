BEGIN;

CREATE TABLE IF NOT EXISTS mo_provider_telemetry (
    telemetry_key CHAR(64) PRIMARY KEY,
    capability TEXT NOT NULL
        CHECK (capability IN ('embedding', 'reranking', 'generation')),
    request_shape TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    request_count BIGINT NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    success_count BIGINT NOT NULL DEFAULT 0 CHECK (success_count >= 0),
    failure_count BIGINT NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    retryable_failure_count BIGINT NOT NULL DEFAULT 0
        CHECK (retryable_failure_count >= 0),
    degraded_count BIGINT NOT NULL DEFAULT 0 CHECK (degraded_count >= 0),
    attempt_count BIGINT NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    retry_count BIGINT NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    last_outcome TEXT CHECK (last_outcome IN ('success', 'failure')),
    last_observed_at TIMESTAMPTZ,
    last_latency_ms INTEGER CHECK (last_latency_ms >= 0),
    last_status_code INTEGER,
    last_error_code TEXT,
    last_failure_kind TEXT,
    last_upstream_status_code INTEGER,
    last_retry_at TIMESTAMPTZ,
    last_retry_delay_ms INTEGER CHECK (last_retry_delay_ms >= 0),
    last_retry_failure_kind TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_mo_provider_telemetry_identity UNIQUE (
        capability,
        request_shape,
        deployment_id,
        model_revision
    ),
    CONSTRAINT ck_mo_provider_telemetry_requests CHECK (
        request_count = success_count + failure_count
    ),
    CONSTRAINT ck_mo_provider_telemetry_attempts CHECK (
        attempt_count = request_count + retry_count
    ),
    CONSTRAINT ck_mo_provider_telemetry_retryable CHECK (
        retryable_failure_count <= failure_count
    ),
    CONSTRAINT ck_mo_provider_telemetry_degraded CHECK (
        degraded_count <= failure_count
    )
);

CREATE INDEX IF NOT EXISTS ix_mo_provider_telemetry_capability
    ON mo_provider_telemetry (capability, updated_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('1154_mo_provider_telemetry', 'MO durable provider telemetry aggregates')
ON CONFLICT (version) DO NOTHING;

COMMIT;
