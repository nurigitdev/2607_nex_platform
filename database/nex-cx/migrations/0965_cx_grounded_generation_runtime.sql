BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE cx_generation_executions
    ADD COLUMN IF NOT EXISTS private_output_schema_version TEXT,
    ADD COLUMN IF NOT EXISTS output_storage_backend TEXT,
    ADD COLUMN IF NOT EXISTS output_storage_uri TEXT,
    ADD COLUMN IF NOT EXISTS output_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS output_size_bytes BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_cx_gen_private_output'
    ) THEN
        ALTER TABLE cx_generation_executions
            ADD CONSTRAINT ck_cx_gen_private_output CHECK (
                (
                    private_output_schema_version IS NULL
                    AND output_storage_backend IS NULL
                    AND output_storage_uri IS NULL
                    AND output_sha256 IS NULL
                    AND output_size_bytes IS NULL
                )
                OR (
                    private_output_schema_version = 'cx_generation_private_output.v1'
                    AND output_storage_backend <> ''
                    AND output_storage_uri ~ '^cx-private://'
                    AND output_sha256 ~ '^[0-9a-f]{64}$'
                    AND output_size_bytes > 0
                )
            );
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS ux_cx_gen_output_uri
    ON cx_generation_executions (output_storage_uri)
    WHERE output_storage_uri IS NOT NULL;

INSERT INTO schema_migrations (version, description)
VALUES (
    '0965_cx_grounded_generation_runtime',
    'CX owner-private grounded generation runtime output references'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
