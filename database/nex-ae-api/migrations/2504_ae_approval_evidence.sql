BEGIN;

CREATE TABLE IF NOT EXISTS ae_approval_evidence (
    tenant_id TEXT NOT NULL
        CHECK (char_length(tenant_id) BETWEEN 1 AND 128),
    agent_execution_id UUID NOT NULL,
    executable_step_id TEXT NOT NULL
        CHECK (char_length(executable_step_id) BETWEEN 1 AND 256),
    nsl_execution_id TEXT NOT NULL
        CHECK (char_length(nsl_execution_id) BETWEEN 1 AND 256),
    business_operation_id TEXT NOT NULL
        CHECK (char_length(business_operation_id) BETWEEN 1 AND 256),
    approval_id TEXT NOT NULL
        CHECK (char_length(approval_id) BETWEEN 1 AND 256),
    approval_request_id TEXT NOT NULL
        CHECK (char_length(approval_request_id) BETWEEN 1 AND 256),
    skill_semantic_hash TEXT NOT NULL
        CHECK (skill_semantic_hash ~ '^sha256:[0-9a-f]{64}$'),
    decision TEXT NOT NULL CHECK (decision IN ('APPROVE', 'REJECT')),
    approver_id TEXT NOT NULL
        CHECK (char_length(approver_id) BETWEEN 1 AND 128),
    decided_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NULL,
    payload_hash TEXT NOT NULL
        CHECK (payload_hash ~ '^sha256:[0-9a-f]{64}$'),
    write_intent_hash TEXT NOT NULL
        CHECK (char_length(write_intent_hash) BETWEEN 1 AND 256),
    approval_work_item_ref UUID NOT NULL,
    oa_decision_ref TEXT NOT NULL
        CHECK (char_length(oa_decision_ref) BETWEEN 1 AND 128),
    protected_request_ref TEXT NOT NULL
        CHECK (protected_request_ref ~
            '^ae://nsl-approval-requests/[0-9a-f]{2}/[0-9a-f]{64}\.json$'),
    evidence_integrity TEXT NOT NULL
        CHECK (evidence_integrity ~ '^sha256:[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, approval_request_id),
    CONSTRAINT ux_ae_approval_evidence_work_item
        UNIQUE (tenant_id, approval_work_item_ref),
    CONSTRAINT fk_ae_approval_evidence_execution
        FOREIGN KEY (tenant_id, agent_execution_id)
        REFERENCES ae_agent_execution (tenant_id, agent_execution_id),
    CONSTRAINT fk_ae_approval_evidence_step
        FOREIGN KEY (tenant_id, executable_step_id)
        REFERENCES ae_executable_step (tenant_id, executable_step_id),
    CONSTRAINT fk_ae_approval_evidence_request
        FOREIGN KEY (
            tenant_id,
            approval_request_id,
            nsl_execution_id,
            business_operation_id
        ) REFERENCES ae_nsl_approval_request (
            tenant_id,
            approval_request_id,
            nsl_execution_id,
            business_operation_id
        )
);

CREATE INDEX IF NOT EXISTS ix_ae_approval_evidence_execution
    ON ae_approval_evidence (
        tenant_id,
        agent_execution_id,
        executable_step_id,
        decided_at DESC
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2504_ae_approval_evidence',
    'P8-S48 immutable AE Platform ApprovalEvidence source of record'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
