BEGIN;

CREATE TABLE IF NOT EXISTS ag_alerts (
    alert_id TEXT PRIMARY KEY,
    dedup_key CHAR(71) NOT NULL UNIQUE,
    rule_id TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    service_id TEXT NOT NULL CHECK (
        service_id IN ('nex-oa', 'nex-ae-api', 'nex-cx', 'nex-mo', 'nex-ag')
    ),
    alert_state TEXT NOT NULL CHECK (
        alert_state IN ('PENDING', 'FIRING', 'ACKNOWLEDGED', 'RESOLVED', 'SUPPRESSED')
    ),
    severity TEXT NOT NULL CHECK (
        severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')
    ),
    reason_code TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL CHECK (occurrence_count > 0),
    state_revision INTEGER NOT NULL CHECK (state_revision > 0),
    first_observed_at TIMESTAMPTZ NOT NULL,
    last_observed_at TIMESTAMPTZ NOT NULL,
    accountable_owner TEXT NOT NULL,
    runbook_ref TEXT NOT NULL,
    suppression_until TIMESTAMPTZ,
    acknowledged_by_hash CHAR(71),
    CONSTRAINT ck_ag_alert_dedup_digest CHECK (dedup_key LIKE 'sha256:%'),
    CONSTRAINT ck_ag_alert_ack_digest CHECK (
        acknowledged_by_hash IS NULL OR acknowledged_by_hash LIKE 'sha256:%'
    )
);

CREATE TABLE IF NOT EXISTS ag_notify_outbox (
    notify_id TEXT PRIMARY KEY,
    alert_id TEXT NOT NULL REFERENCES ag_alerts(alert_id) ON DELETE CASCADE,
    idempotency_key_hash CHAR(71) NOT NULL UNIQUE,
    channel TEXT NOT NULL CHECK (
        channel IN ('LOCAL', 'INTERNAL_WEBHOOK', 'EXTERNAL_WEBHOOK')
    ),
    route_alias TEXT NOT NULL,
    payload_hash CHAR(71) NOT NULL,
    delivery_state TEXT NOT NULL CHECK (
        delivery_state IN ('PENDING', 'CLAIMED', 'DELIVERED', 'RETRY_WAIT', 'BLOCKED', 'DEAD_LETTER')
    ),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at TIMESTAMPTZ,
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    last_error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    delivered_at TIMESTAMPTZ,
    CONSTRAINT ck_ag_notify_digests CHECK (
        idempotency_key_hash LIKE 'sha256:%' AND payload_hash LIKE 'sha256:%'
    )
);

CREATE TABLE IF NOT EXISTS ag_notify_attempts (
    attempt_id TEXT PRIMARY KEY,
    notify_id TEXT NOT NULL REFERENCES ag_notify_outbox(notify_id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    outcome TEXT NOT NULL CHECK (
        outcome IN ('DELIVERED', 'RETRY_WAIT', 'BLOCKED', 'DEAD_LETTER')
    ),
    response_code INTEGER CHECK (response_code BETWEEN 100 AND 599),
    receipt_digest CHAR(71),
    error_code TEXT,
    attempted_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_ag_notify_attempt UNIQUE (notify_id, attempt_number),
    CONSTRAINT ck_ag_notify_receipt_digest CHECK (
        receipt_digest IS NULL OR receipt_digest LIKE 'sha256:%'
    )
);

CREATE INDEX IF NOT EXISTS ix_ag_alert_operations
    ON ag_alerts (alert_state, severity, last_observed_at DESC);
CREATE INDEX IF NOT EXISTS ix_ag_alert_service_policy
    ON ag_alerts (service_id, policy_id, last_observed_at DESC);
CREATE INDEX IF NOT EXISTS ix_ag_notify_claim
    ON ag_notify_outbox (delivery_state, next_attempt_at, lease_expires_at, created_at);
CREATE INDEX IF NOT EXISTS ix_ag_notify_alert
    ON ag_notify_outbox (alert_id, created_at);
CREATE INDEX IF NOT EXISTS ix_ag_notify_attempt_history
    ON ag_notify_attempts (notify_id, attempt_number);

INSERT INTO schema_migrations (version, description)
VALUES ('1477_ag_platform_alert_persistence', 'AG platform alert and notification outbox persistence')
ON CONFLICT (version) DO NOTHING;

COMMIT;
