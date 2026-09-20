BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ag_ret_archives (
    archive_id TEXT PRIMARY KEY,
    receipt_schema_version TEXT NOT NULL DEFAULT 'ag_archive_receipt.v1'
        CHECK (receipt_schema_version = 'ag_archive_receipt.v1'),
    source_kind TEXT NOT NULL CHECK (
        source_kind IN ('operational_event', 'evidence_export')
    ),
    source_id TEXT NOT NULL,
    source_content_sha256 TEXT NOT NULL CHECK (
        source_content_sha256 ~ '^[0-9a-f]{64}$'
    ),
    archive_provider_mode TEXT NOT NULL CHECK (
        archive_provider_mode IN ('mock', 'external')
    ),
    archive_object_ref_hash TEXT NOT NULL CHECK (
        archive_object_ref_hash ~ '^[0-9a-f]{64}$'
    ),
    archive_receipt_sha256 TEXT NOT NULL CHECK (
        archive_receipt_sha256 ~ '^[0-9a-f]{64}$'
    ),
    archive_status TEXT NOT NULL CHECK (
        archive_status IN ('REQUESTED', 'MOCKED', 'SEALED', 'FAILED', 'PURGED')
    ),
    archived_at TIMESTAMPTZ NOT NULL,
    purge_after TIMESTAMPTZ,
    purged_at TIMESTAMPTZ,
    failure_code TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_kind, source_id),
    CHECK (
        (archive_status = 'SEALED' AND archive_provider_mode = 'external'
            AND purge_after IS NOT NULL)
        OR archive_status <> 'SEALED'
    ),
    CHECK (
        (archive_status = 'MOCKED' AND archive_provider_mode = 'mock'
            AND purge_after IS NULL)
        OR archive_status <> 'MOCKED'
    )
);

CREATE INDEX IF NOT EXISTS idx_ag_ret_arc_status_due
    ON ag_ret_archives (archive_status, purge_after, archive_id);

INSERT INTO schema_migrations (version, description)
VALUES ('0884_ag_retention_archive_receipts', 'AG retention archive receipt and purge tombstone persistence')
ON CONFLICT (version) DO NOTHING;

COMMIT;
