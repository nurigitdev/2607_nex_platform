BEGIN;

ALTER TABLE ae_wait_registration
    ALTER COLUMN external_ref TYPE TEXT USING external_ref::TEXT;

ALTER TABLE ae_wait_registration
    DROP CONSTRAINT IF EXISTS ae_wait_registration_wait_type_check;

ALTER TABLE ae_wait_registration
    DROP CONSTRAINT IF EXISTS ck_ae_wait_registration_type;

ALTER TABLE ae_wait_registration
    ADD CONSTRAINT ck_ae_wait_registration_type
    CHECK (wait_type IN ('WORK_RESULT', 'NSL_APPROVAL'));

ALTER TABLE ae_wait_registration
    DROP CONSTRAINT IF EXISTS ck_ae_wait_registration_external_ref;

ALTER TABLE ae_wait_registration
    ADD CONSTRAINT ck_ae_wait_registration_external_ref
    CHECK (char_length(external_ref) BETWEEN 1 AND 256);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2502_ae_wait_registration_generalization',
    'P8-S45 string external reference and typed AE wait registration'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
