BEGIN;

ALTER TABLE eos_business_operation
    DROP CONSTRAINT ck_eos_bo_operation,
    ADD CONSTRAINT ck_eos_bo_operation
        CHECK (operation ~ '^[A-Z][A-Z0-9_.]{0,127}$');

ALTER TABLE eos_idempotency
    DROP CONSTRAINT ck_eos_idem_operation,
    ADD CONSTRAINT ck_eos_idem_operation
        CHECK (operation ~ '^[A-Z][A-Z0-9_.]{0,127}$');

INSERT INTO schema_migrations (version, description)
VALUES (
    '2508_eos_operation_name_compatibility',
    'Align EOS persisted operation names with canonical dotted finance operations'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
