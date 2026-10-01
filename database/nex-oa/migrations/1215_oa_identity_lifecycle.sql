BEGIN;

ALTER TABLE oa_subjects
    ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1;

ALTER TABLE oa_tenant_memberships
    ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS oa_id_lifecycle_events (
    event_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    subject_ref_type TEXT NOT NULL DEFAULT 'oa.user'
        CHECK (subject_ref_type = 'oa.user'),
    subject_id TEXT NOT NULL,
    entity_type TEXT NOT NULL
        CHECK (entity_type IN ('SUBJECT', 'MEMBERSHIP')),
    previous_status TEXT NOT NULL,
    target_status TEXT NOT NULL,
    previous_revision BIGINT NOT NULL CHECK (previous_revision > 0),
    next_revision BIGINT NOT NULL CHECK (next_revision > previous_revision),
    reason_code TEXT NOT NULL CHECK (char_length(reason_code) BETWEEN 2 AND 64),
    actor_ref_type TEXT NOT NULL,
    actor_ref_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_oa_id_lifecycle_subject
        FOREIGN KEY (tenant_id, subject_ref_type, subject_id)
        REFERENCES oa_subjects (tenant_id, subject_ref_type, subject_id),
    CONSTRAINT uq_oa_id_lifecycle_entity_rev
        UNIQUE (tenant_id, subject_id, entity_type, next_revision)
);

CREATE INDEX IF NOT EXISTS ix_oa_id_lifecycle_subject_time
    ON oa_id_lifecycle_events (tenant_id, subject_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS ix_oa_id_lifecycle_entity_time
    ON oa_id_lifecycle_events (entity_type, occurred_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('1215_oa_identity_lifecycle', 'OA revisioned identity lifecycle and event history')
ON CONFLICT (version) DO NOTHING;

COMMIT;
