BEGIN;

ALTER TABLE oa_service_principals
    DROP CONSTRAINT IF EXISTS oa_service_principals_service_id_check;

ALTER TABLE oa_service_principals
    ADD CONSTRAINT oa_service_principals_service_id_check
    CHECK (
        service_id IN (
            'nex-oa',
            'nex-ag',
            'nex-ae-api',
            'nex-cx',
            'nex-mo',
            'nex-wc',
            'nex-eos'
        )
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2516_oa_service_principal_wc_eos',
    'Admit WC and EOS service principals for signed Demo trust'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
