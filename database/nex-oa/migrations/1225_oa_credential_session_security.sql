BEGIN;

ALTER TABLE oa_local_credentials
    DROP CONSTRAINT IF EXISTS oa_local_credentials_password_hash_algorithm_check;

ALTER TABLE oa_local_credentials
    DROP CONSTRAINT IF EXISTS ck_oa_local_credentials_hash_algorithm;

ALTER TABLE oa_local_credentials
    ADD CONSTRAINT ck_oa_local_credentials_hash_algorithm
    CHECK (password_hash_algorithm IN ('pbkdf2_sha256.v1', 'argon2id.v1'));

ALTER TABLE oa_user_sessions
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;

ALTER TABLE oa_user_sessions
    ADD COLUMN IF NOT EXISTS idle_expires_at TIMESTAMPTZ;

UPDATE oa_user_sessions
SET
    last_seen_at = COALESCE(last_seen_at, issued_at),
    idle_expires_at = COALESCE(
        idle_expires_at,
        LEAST(expires_at, issued_at + INTERVAL '30 minutes')
    )
WHERE last_seen_at IS NULL OR idle_expires_at IS NULL;

ALTER TABLE oa_user_sessions
    ALTER COLUMN last_seen_at SET NOT NULL;

ALTER TABLE oa_user_sessions
    ALTER COLUMN idle_expires_at SET NOT NULL;

ALTER TABLE oa_user_sessions
    DROP CONSTRAINT IF EXISTS ck_oa_user_sessions_idle_time;

ALTER TABLE oa_user_sessions
    ADD CONSTRAINT ck_oa_user_sessions_idle_time
    CHECK (
        last_seen_at >= issued_at
        AND idle_expires_at > last_seen_at
        AND idle_expires_at <= expires_at
    );

CREATE INDEX IF NOT EXISTS ix_oa_sessions_active_idle
    ON oa_user_sessions (status, idle_expires_at, expires_at);

CREATE TABLE IF NOT EXISTS oa_auth_events (
    event_id TEXT PRIMARY KEY,
    event_schema_version TEXT NOT NULL DEFAULT 'oa_auth_event.v1'
        CHECK (event_schema_version = 'oa_auth_event.v1'),
    event_type TEXT NOT NULL,
    outcome TEXT NOT NULL
        CHECK (outcome IN ('SUCCEEDED', 'FAILED', 'BLOCKED')),
    tenant_id TEXT,
    subject_id TEXT,
    credential_id TEXT,
    actor_ref TEXT NOT NULL,
    request_id TEXT,
    trace_id TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(details) = 'object'),
    occurred_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_oa_auth_events_tenant_time
    ON oa_auth_events (tenant_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS ix_oa_auth_events_subject_time
    ON oa_auth_events (subject_id, occurred_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '1225_oa_credential_session_security',
    'OA credential hash, secure session expiry, and auth event persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
