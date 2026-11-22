BEGIN;

CREATE INDEX IF NOT EXISTS ix_wc_work_item_dispatch_scan
    ON wc_work_item (state, created_at, tenant_id, work_item_id)
    WHERE state IN ('CREATED', 'ROUTED');

INSERT INTO schema_migrations (version, description)
VALUES (
    '1007_wc_assignment_dispatch_scan',
    'WC assignment dispatcher bounded claimable WorkItem scan'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
