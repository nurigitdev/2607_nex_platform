BEGIN;

ALTER TABLE eos_voucher_draft
    ADD COLUMN IF NOT EXISTS attachment_batch_id UUID NULL,
    ADD COLUMN IF NOT EXISTS attachment_manifest_hash VARCHAR(71) NULL;

ALTER TABLE eos_voucher_draft
    DROP CONSTRAINT IF EXISTS ck_eos_voucher_attachment_lineage;

ALTER TABLE eos_voucher_draft
    ADD CONSTRAINT ck_eos_voucher_attachment_lineage CHECK (
        (attachment_batch_id IS NULL AND attachment_manifest_hash IS NULL)
        OR
        (
            attachment_batch_id IS NOT NULL
            AND attachment_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
        )
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2513_eos_voucher_attachment_lineage',
    'NeX-EOS approval-locked Voucher attachment manifest lineage'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
