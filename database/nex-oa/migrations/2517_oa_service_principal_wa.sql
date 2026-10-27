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
            'nex-eos',
            'nex-wa'
        )
    );

ALTER TABLE oa_token_revocations
    DROP CONSTRAINT IF EXISTS oa_token_revocations_audience_check;

ALTER TABLE oa_token_revocations
    ADD CONSTRAINT oa_token_revocations_audience_check
    CHECK (
        audience IN (
            'nex-oa',
            'nex-ag',
            'nex-ae-api',
            'nex-cx',
            'nex-mo',
            'nex-wc',
            'nex-eos',
            'nex-wa'
        )
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2517_oa_service_principal_wa',
    'Admit WA service principals and token audience'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
