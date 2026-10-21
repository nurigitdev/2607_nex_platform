BEGIN;

CREATE TABLE IF NOT EXISTS eos_voucher_draft_attachment (
    tenant_id VARCHAR(128) NOT NULL,
    attachment_id UUID NOT NULL,
    voucher_id UUID NOT NULL,
    object_ref VARCHAR(256) NOT NULL,
    storage_owner VARCHAR(128) NOT NULL,
    object_version_ref VARCHAR(128) NULL,
    display_name VARCHAR(512) NOT NULL,
    media_type VARCHAR(192) NOT NULL,
    size_bytes BIGINT NOT NULL,
    content_sha256 VARCHAR(64) NOT NULL,
    evidence_ref VARCHAR(128) NULL,
    resolver_authenticated BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_voucher_attachment
        PRIMARY KEY (tenant_id, attachment_id),
    CONSTRAINT fk_eos_attachment_voucher
        FOREIGN KEY (tenant_id, voucher_id)
        REFERENCES eos_voucher_draft (tenant_id, voucher_id)
        ON DELETE CASCADE,
    CONSTRAINT ux_eos_attachment_object
        UNIQUE (tenant_id, voucher_id, object_ref),
    CONSTRAINT ck_eos_attachment_size CHECK (size_bytes >= 0),
    CONSTRAINT ck_eos_attachment_auth CHECK (resolver_authenticated = TRUE)
);

CREATE INDEX IF NOT EXISTS ix_eos_attachment_voucher
    ON eos_voucher_draft_attachment (tenant_id, voucher_id, created_at);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2507_eos_voucher_attachment',
    'NeX-EOS Voucher attachment metadata and opaque object reference model'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
