BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE ae_claim_handoff_inbox
    ADD COLUMN IF NOT EXISTS planning_source_json JSONB NULL;

ALTER TABLE ae_claim_handoff_inbox
    ADD CONSTRAINT ck_ae_claim_planning_source_json CHECK (
        planning_source_json IS NULL
        OR jsonb_typeof(planning_source_json) = 'object'
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2405_ae_claimed_planning_source',
    'Persist bounded claimed WorkItem planning source in the AE handoff inbox'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
