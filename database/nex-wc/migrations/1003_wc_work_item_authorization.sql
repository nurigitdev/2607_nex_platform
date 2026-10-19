BEGIN;

ALTER TABLE wc_work_item
    ADD COLUMN IF NOT EXISTS create_authorization_revision_hash TEXT NULL,
    ADD COLUMN IF NOT EXISTS create_authorization_checked_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS create_authorized_subject_id TEXT NULL;

INSERT INTO schema_migrations (version, description)
VALUES (
    '1003_wc_work_item_authorization',
    'WC WorkItem create authorization evidence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
