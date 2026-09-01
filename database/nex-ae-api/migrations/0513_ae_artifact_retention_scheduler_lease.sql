BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_artifact_retention_scheduler_leases (
    scheduler_id TEXT PRIMARY KEY,
    lease_record_id TEXT NOT NULL,
    lease_record_schema_version TEXT NOT NULL
        DEFAULT 'ae_artifact_retention_scheduler_lease_record.v1'
        CHECK (
            lease_record_schema_version =
            'ae_artifact_retention_scheduler_lease_record.v1'
        ),
    service_id TEXT NOT NULL DEFAULT 'nex-ae-api'
        CHECK (service_id = 'nex-ae-api'),
    lease_owner_id TEXT NOT NULL,
    lease_token TEXT NOT NULL,
    lease_status TEXT NOT NULL
        CHECK (lease_status IN ('HELD', 'RELEASED', 'EXPIRED')),
    fencing_token BIGINT NOT NULL CHECK (fencing_token >= 1),
    acquired_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    released_at TIMESTAMPTZ,
    last_observed_at TIMESTAMPTZ NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('manual_tick_once')),
    tick_id TEXT,
    idempotency_key TEXT NOT NULL,
    guardrails JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(guardrails) = 'object'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_ae_artifact_retention_scheduler_lease_times
        CHECK (expires_at > acquired_at),
    CONSTRAINT ck_ae_artifact_retention_scheduler_lease_release
        CHECK (
            (
                lease_status = 'RELEASED'
                AND released_at IS NOT NULL
            )
            OR (
                lease_status <> 'RELEASED'
                AND released_at IS NULL
            )
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ae_artifact_retention_scheduler_leases_record
    ON ae_artifact_retention_scheduler_leases (lease_record_id);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_retention_scheduler_leases_status_expires
    ON ae_artifact_retention_scheduler_leases (lease_status, expires_at);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_retention_scheduler_leases_owner
    ON ae_artifact_retention_scheduler_leases (lease_owner_id);

CREATE INDEX IF NOT EXISTS idx_ae_artifact_retention_scheduler_leases_idempotency
    ON ae_artifact_retention_scheduler_leases (scheduler_id, idempotency_key);

INSERT INTO schema_migrations (version, description)
VALUES (
    '0513_ae_artifact_retention_scheduler_lease',
    'AE artifact retention scheduler lease repository foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
