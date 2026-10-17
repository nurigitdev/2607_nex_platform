BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_semantic_candidate (
    tenant_id TEXT NOT NULL,
    candidate_id UUID NOT NULL,
    owner_subject_id TEXT NOT NULL,
    agent_execution_id UUID NOT NULL,
    semantic_stage TEXT NOT NULL CHECK (semantic_stage IN ('INTENT', 'CONTEXT', 'PLAN')),
    candidate_revision INTEGER NOT NULL CHECK (candidate_revision BETWEEN 1 AND 99),
    candidate_hash TEXT NULL CHECK (
        candidate_hash IS NULL OR candidate_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    candidate_payload_storage_ref TEXT NULL,
    candidate_payload_size_bytes BIGINT NULL CHECK (
        candidate_payload_size_bytes IS NULL
        OR candidate_payload_size_bytes BETWEEN 1 AND 1048576
    ),
    provider_output_sha256 TEXT NOT NULL CHECK (
        provider_output_sha256 ~ '^[0-9a-f]{64}$'
    ),
    input_context_hash TEXT NOT NULL CHECK (
        input_context_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    prompt_binding_id UUID NOT NULL,
    prompt_binding_key TEXT NOT NULL,
    prompt_template_version_id UUID NOT NULL,
    prompt_template_version TEXT NOT NULL,
    prompt_content_sha256 TEXT NOT NULL CHECK (
        prompt_content_sha256 ~ '^[0-9a-f]{64}$'
    ),
    rendered_prompt_hash TEXT NOT NULL CHECK (
        rendered_prompt_hash ~ '^[0-9a-f]{64}$'
    ),
    model_profile TEXT NOT NULL,
    model_ref TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    mo_generation_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    admission_policy_ref TEXT NOT NULL,
    validation_outcome TEXT NOT NULL CHECK (
        validation_outcome IN ('ADMITTED', 'REJECTED', 'FAILED')
    ),
    directive TEXT NOT NULL CHECK (directive IN (
        'CONTINUE', 'SHADOW_ONLY', 'CLARIFICATION_REQUIRED',
        'CONTEXT_REFRESH_REQUIRED', 'REPLAN_REQUIRED', 'BLOCKED'
    )),
    failure_code TEXT NULL CHECK (
        failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{2,127}$'
    ),
    evidence_json JSONB NOT NULL CHECK (jsonb_typeof(evidence_json) = 'object'),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, candidate_id),
    CONSTRAINT ux_ae_sem_candidate_stage
        UNIQUE (tenant_id, agent_execution_id, semantic_stage, candidate_revision),
    CONSTRAINT fk_ae_sem_candidate_execution
        FOREIGN KEY (tenant_id, agent_execution_id)
        REFERENCES ae_agent_execution (tenant_id, agent_execution_id),
    CONSTRAINT ck_ae_sem_candidate_admitted CHECK (
        validation_outcome <> 'ADMITTED'
        OR (
            directive = 'CONTINUE'
            AND failure_code IS NULL
            AND candidate_hash IS NOT NULL
            AND candidate_payload_storage_ref IS NOT NULL
            AND candidate_payload_size_bytes IS NOT NULL
        )
    ),
    CONSTRAINT ck_ae_sem_candidate_json_identity CHECK (
        evidence_json ->> 'schema_version' = 'p65.semantic_candidate_evidence.v1'
        AND evidence_json ->> 'tenant_id' = tenant_id
        AND evidence_json ->> 'candidate_id' = candidate_id::text
        AND evidence_json ->> 'execution_id' = agent_execution_id::text
        AND evidence_json ->> 'semantic_stage' = semantic_stage
        AND (evidence_json ->> 'candidate_revision')::integer = candidate_revision
    )
);

CREATE INDEX IF NOT EXISTS idx_ae_sem_candidate_execution
    ON ae_semantic_candidate (
        tenant_id, agent_execution_id, semantic_stage, candidate_revision
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2300_ae_semantic_candidate',
    'P6.5 bounded semantic candidate evidence persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
