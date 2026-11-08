BEGIN;

CREATE TABLE IF NOT EXISTS ae_voucher_attach_batch (
    tenant_id TEXT NOT NULL
        CHECK (char_length(tenant_id) BETWEEN 1 AND 128),
    attachment_batch_id UUID NOT NULL,
    owner_subject_id TEXT NOT NULL
        CHECK (char_length(owner_subject_id) BETWEEN 1 AND 128),
    conversation_id UUID NOT NULL,
    interaction_id UUID NOT NULL,
    state TEXT NOT NULL
        CHECK (state IN (
            'DRAFT', 'UPLOADING', 'READY', 'QUARANTINED',
            'FAILED', 'LOCKED', 'ABANDONED'
        )),
    attachment_count INTEGER NOT NULL DEFAULT 0
        CHECK (attachment_count BETWEEN 0 AND 20),
    total_size_bytes BIGINT NOT NULL DEFAULT 0
        CHECK (total_size_bytes BETWEEN 0 AND 104857600),
    attachment_manifest_hash TEXT NULL
        CHECK (
            attachment_manifest_hash IS NULL
            OR attachment_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
        ),
    locked_at TIMESTAMPTZ NULL,
    trace_id TEXT NOT NULL CHECK (char_length(trace_id) BETWEEN 1 AND 128),
    correlation_id TEXT NOT NULL
        CHECK (char_length(correlation_id) BETWEEN 1 AND 128),
    causation_id TEXT NOT NULL
        CHECK (char_length(causation_id) BETWEEN 1 AND 128),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, attachment_batch_id),
    CONSTRAINT ux_ae_voucher_attach_interaction
        UNIQUE (tenant_id, conversation_id, interaction_id),
    CONSTRAINT ck_ae_voucher_attach_lock
        CHECK (
            (state = 'LOCKED' AND locked_at IS NOT NULL
                AND attachment_manifest_hash IS NOT NULL)
            OR
            (state <> 'LOCKED' AND locked_at IS NULL)
        )
);

CREATE TABLE IF NOT EXISTS ae_voucher_attachment (
    tenant_id TEXT NOT NULL
        CHECK (char_length(tenant_id) BETWEEN 1 AND 128),
    attachment_batch_id UUID NOT NULL,
    attachment_id UUID NOT NULL,
    state TEXT NOT NULL
        CHECK (state IN (
            'UPLOADING', 'READY', 'QUARANTINED',
            'FAILED', 'LOCKED', 'REMOVED'
        )),
    display_name TEXT NOT NULL
        CHECK (char_length(display_name) BETWEEN 1 AND 255),
    media_type TEXT NOT NULL
        CHECK (char_length(media_type) BETWEEN 3 AND 192),
    size_bytes BIGINT NOT NULL
        CHECK (size_bytes BETWEEN 1 AND 26214400),
    content_sha256 TEXT NULL
        CHECK (
            content_sha256 IS NULL
            OR content_sha256 ~ '^[0-9a-f]{64}$'
        ),
    object_ref TEXT NULL
        CHECK (object_ref IS NULL OR char_length(object_ref) BETWEEN 16 AND 256),
    object_version_ref TEXT NULL
        CHECK (
            object_version_ref IS NULL
            OR char_length(object_version_ref) BETWEEN 1 AND 128
        ),
    scan_status TEXT NOT NULL
        CHECK (scan_status IN ('PENDING', 'CLEAN', 'REJECTED', 'UNAVAILABLE')),
    evidence_ref TEXT NULL
        CHECK (evidence_ref IS NULL OR char_length(evidence_ref) BETWEEN 1 AND 128),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, attachment_batch_id, attachment_id),
    CONSTRAINT fk_ae_voucher_attachment_batch
        FOREIGN KEY (tenant_id, attachment_batch_id)
        REFERENCES ae_voucher_attach_batch (tenant_id, attachment_batch_id)
        ON DELETE CASCADE,
    CONSTRAINT ux_ae_voucher_attachment_object
        UNIQUE (tenant_id, object_ref),
    CONSTRAINT ck_ae_voucher_attachment_publication
        CHECK (
            (state IN ('UPLOADING', 'FAILED', 'REMOVED')
                AND object_ref IS NULL)
            OR
            (state IN ('READY', 'QUARANTINED', 'LOCKED')
                AND object_ref IS NOT NULL
                AND content_sha256 IS NOT NULL)
        )
);

CREATE INDEX IF NOT EXISTS ix_ae_voucher_attach_owner
    ON ae_voucher_attach_batch (
        tenant_id,
        owner_subject_id,
        updated_at DESC
    );

CREATE INDEX IF NOT EXISTS ix_ae_voucher_attachment_batch_state
    ON ae_voucher_attachment (
        tenant_id,
        attachment_batch_id,
        state,
        attachment_id
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2513_ae_voucher_attachment',
    'P8-S75B durable owner-scoped Voucher attachment batch and item persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
