BEGIN;

DROP INDEX IF EXISTS ux_ae_wait_product_external;

CREATE UNIQUE INDEX ux_ae_wait_product_external
    ON ae_wait_registration (
        tenant_id, agent_execution_id, external_ref, wait_type
    )
    WHERE wait_type = 'PRODUCT_PREPARATION' AND state = 'PENDING';

INSERT INTO schema_migrations (version, description)
VALUES (
    '2519_ae_product_wait_active_authority',
    'Allow append-only Product correction waits while admitting one pending authority'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
