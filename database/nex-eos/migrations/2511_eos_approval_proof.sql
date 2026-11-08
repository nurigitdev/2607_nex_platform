BEGIN;

ALTER TABLE eos_approval_stage
    DROP CONSTRAINT IF EXISTS ck_eos_approval_stage_activation;

ALTER TABLE eos_approval_stage
    ADD CONSTRAINT ck_eos_approval_stage_activation CHECK (
        state IN ('WAITING', 'CANCELLED') OR activated_at IS NOT NULL
    );

CREATE TABLE IF NOT EXISTS eos_approval_proof (
    tenant_id VARCHAR(128) NOT NULL,
    approval_proof_id UUID NOT NULL,
    approval_instance_id UUID NOT NULL,
    business_operation_id UUID NOT NULL,
    final_approval_stage_id UUID NOT NULL,
    final_wc_decision_id UUID NOT NULL,
    approval_domain VARCHAR(32) NOT NULL,
    protected_operation_ref VARCHAR(256) NOT NULL,
    payload_hash VARCHAR(71) NOT NULL,
    write_intent_hash VARCHAR(71) NOT NULL,
    policy_hash VARCHAR(71) NOT NULL,
    instance_binding_hash VARCHAR(71) NOT NULL,
    decision_chain_hash VARCHAR(71) NOT NULL,
    final_decision_hash VARCHAR(71) NOT NULL,
    proof_version INTEGER NOT NULL,
    proof_hash VARCHAR(71) NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_approval_proof
        PRIMARY KEY (tenant_id, approval_proof_id),
    CONSTRAINT ux_eos_approval_proof_instance
        UNIQUE (tenant_id, approval_instance_id),
    CONSTRAINT ux_eos_approval_proof_hash
        UNIQUE (tenant_id, proof_hash),
    CONSTRAINT fk_eos_approval_proof_instance
        FOREIGN KEY (tenant_id, approval_instance_id)
        REFERENCES eos_approval_instance (tenant_id, approval_instance_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_eos_approval_proof_operation
        FOREIGN KEY (tenant_id, business_operation_id)
        REFERENCES eos_business_operation (tenant_id, business_operation_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_eos_approval_proof_stage
        FOREIGN KEY (
            tenant_id,
            approval_instance_id,
            final_approval_stage_id
        )
        REFERENCES eos_approval_stage (
            tenant_id,
            approval_instance_id,
            approval_stage_id
        )
        ON DELETE RESTRICT,
    CONSTRAINT ck_eos_approval_proof_domain CHECK (
        approval_domain = 'BUSINESS_FORMAL'
    ),
    CONSTRAINT ck_eos_approval_proof_payload_hash CHECK (
        payload_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_approval_proof_intent_hash CHECK (
        write_intent_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_approval_proof_policy_hash CHECK (
        policy_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_approval_proof_binding_hash CHECK (
        instance_binding_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_approval_proof_chain_hash CHECK (
        decision_chain_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_approval_proof_decision_hash CHECK (
        final_decision_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_approval_proof_hash CHECK (
        proof_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_approval_proof_version CHECK (proof_version > 0)
);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2511_eos_approval_proof',
    'NeX-EOS immutable final approval proof and stage-transition support'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
