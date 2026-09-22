BEGIN;

ALTER TABLE cx_retrieval_evidence_items
    ALTER COLUMN evidence_text_preview DROP NOT NULL;

INSERT INTO schema_migrations (version, description)
VALUES (
    '0949_cx_retrieval_private_preview_nullable',
    'Allow hash-only evidence persistence for private owner-scoped retrieval packages'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
