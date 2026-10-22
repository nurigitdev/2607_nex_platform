BEGIN;

CREATE TABLE IF NOT EXISTS ae_nsl_approval_request (
    tenant_id TEXT NOT NULL
        CHECK (char_length(tenant_id) BETWEEN 1 AND 128),
    approval_request_id TEXT NOT NULL
        CHECK (char_length(approval_request_id) BETWEEN 1 AND 256),
    nsl_execution_id TEXT NOT NULL
        CHECK (char_length(nsl_execution_id) BETWEEN 1 AND 256),
    business_operation_id TEXT NOT NULL
        CHECK (char_length(business_operation_id) BETWEEN 1 AND 256),
    protected_request_ref TEXT NOT NULL
        CHECK (protected_request_ref ~
            '^ae://nsl-approval-requests/[0-9a-f]{2}/[0-9a-f]{64}\.json$'),
    approval_request_hash TEXT NOT NULL
        CHECK (approval_request_hash ~ '^sha256:[0-9a-f]{64}$'),
    request_size_bytes BIGINT NOT NULL
        CHECK (request_size_bytes BETWEEN 1 AND 1048576),
    content_type TEXT NOT NULL CHECK (content_type = 'application/json'),
    data_classification TEXT NOT NULL CHECK (
        data_classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')
    ),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, approval_request_id),
    CONSTRAINT ux_ae_nsl_approval_request_ref UNIQUE (
        tenant_id, protected_request_ref
    )
);

CREATE INDEX IF NOT EXISTS ix_ae_nsl_approval_business_operation
    ON ae_nsl_approval_request (tenant_id, business_operation_id);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2500_ae_nsl_approval_request',
    'P8 protected canonical NSL ApprovalRequest metadata'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
