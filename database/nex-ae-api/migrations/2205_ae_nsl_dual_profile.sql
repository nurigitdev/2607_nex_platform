BEGIN;

ALTER TABLE ae_nsl_step_execution
    DROP CONSTRAINT IF EXISTS ae_nsl_step_execution_backend_profile_check,
    DROP CONSTRAINT IF EXISTS ck_ae_nsl_step_profile;

ALTER TABLE ae_nsl_step_execution
    ADD CONSTRAINT ck_ae_nsl_step_profile CHECK (
        backend_profile IN (
            'NSL_V01_IN_PROCESS',
            'NSL_V01_PROCESS_ISOLATED'
        )
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2205_ae_nsl_dual_profile',
    'P6 dual-profile NSL binding persistence compatibility'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
