BEGIN;

ALTER TABLE cx_vector_indexes
    DROP CONSTRAINT IF EXISTS ck_cx_vector_indexes_ready;

ALTER TABLE cx_vector_indexes
    ADD CONSTRAINT ck_cx_vector_indexes_ready CHECK (
        (
            status = 'READY'
            AND payload_count = source_chunk_count
            AND payload_fingerprint IS NOT NULL
            AND ready_at IS NOT NULL
        )
        OR (
            status = 'BUILDING'
            AND payload_count = 0
            AND payload_fingerprint IS NULL
            AND ready_at IS NULL
        )
        OR status IN ('STALE', 'REBUILD_REQUIRED', 'FAILED')
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '0936_cx_vector_ready_history',
    'Preserve CX vector READY timestamp and payload receipt history after staleness'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
