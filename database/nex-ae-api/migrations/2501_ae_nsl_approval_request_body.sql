BEGIN;

ALTER TABLE ae_nsl_approval_request
    ADD COLUMN IF NOT EXISTS approval_request_bytes BYTEA;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM ae_nsl_approval_request
        WHERE approval_request_bytes IS NULL
    ) THEN
        RAISE EXCEPTION
            'ae_nsl_approval_request contains metadata-only rows; canonical bytes require an explicit backfill';
    END IF;
END
$$;

ALTER TABLE ae_nsl_approval_request
    ALTER COLUMN approval_request_bytes SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_ae_nsl_approval_request_bytes_size'
          AND conrelid = 'ae_nsl_approval_request'::regclass
    ) THEN
        ALTER TABLE ae_nsl_approval_request
            ADD CONSTRAINT ck_ae_nsl_approval_request_bytes_size
            CHECK (octet_length(approval_request_bytes) BETWEEN 1 AND 1048576);
    END IF;
END
$$;

COMMENT ON COLUMN ae_nsl_approval_request.approval_request_bytes IS
    'Exact canonical NSL ApprovalRequest JSON bytes; private AE PostgreSQL evidence';

INSERT INTO schema_migrations (version, description)
VALUES (
    '2501_ae_nsl_approval_request_body',
    'P8-S44A canonical ApprovalRequest PostgreSQL BYTEA body'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
