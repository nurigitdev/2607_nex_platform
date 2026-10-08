BEGIN;

CREATE TABLE IF NOT EXISTS mo_model_rollouts (
    rollout_id TEXT PRIMARY KEY,
    capability TEXT NOT NULL
        CHECK (capability IN ('embedding', 'reranking', 'generation')),
    alias TEXT NOT NULL,
    catalog_id TEXT NOT NULL REFERENCES mo_model_catalog(catalog_id),
    model_revision TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    artifact_digest CHAR(71) NOT NULL,
    runtime_engine TEXT NOT NULL,
    precision TEXT NOT NULL,
    request_shape_hash CHAR(71) NOT NULL,
    identity_fingerprint CHAR(71) NOT NULL,
    rollout_state TEXT NOT NULL
        CHECK (rollout_state IN (
            'REGISTERED', 'VALIDATING', 'READY', 'CANARY', 'BLOCKED',
            'ACTIVE', 'ROLLED_BACK'
        )),
    state_revision INTEGER NOT NULL CHECK (state_revision > 0),
    lkg_binding_id TEXT NOT NULL REFERENCES mo_alias_bindings(binding_id),
    lkg_identity_fingerprint CHAR(71) NOT NULL,
    readiness_digest CHAR(71),
    calibration_profile_id TEXT,
    calibration_profile_hash CHAR(71),
    reservation_id TEXT,
    canary_policy_hash CHAR(71),
    canary_status TEXT,
    activated_binding_id TEXT REFERENCES mo_alias_bindings(binding_id),
    failure_code TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_mo_rollout_digest_prefix CHECK (
        artifact_digest LIKE 'sha256:%'
        AND request_shape_hash LIKE 'sha256:%'
        AND identity_fingerprint LIKE 'sha256:%'
        AND lkg_identity_fingerprint LIKE 'sha256:%'
    )
);

CREATE TABLE IF NOT EXISTS mo_rollout_events (
    event_id TEXT PRIMARY KEY,
    rollout_id TEXT NOT NULL REFERENCES mo_model_rollouts(rollout_id),
    event_type TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    state_revision INTEGER NOT NULL CHECK (state_revision > 0),
    evidence_digest CHAR(71),
    failure_code TEXT,
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_mo_rollout_event_revision UNIQUE (
        rollout_id,
        state_revision
    )
);

CREATE INDEX IF NOT EXISTS ix_mo_rollout_operations
    ON mo_model_rollouts (capability, alias, rollout_state, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_mo_rollout_identity
    ON mo_model_rollouts (identity_fingerprint, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_mo_rollout_event_history
    ON mo_rollout_events (rollout_id, state_revision ASC);

INSERT INTO schema_migrations (version, description)
VALUES ('1470_mo_model_rollout_persistence', 'MO model rollout state and event persistence')
ON CONFLICT (version) DO NOTHING;

COMMIT;
