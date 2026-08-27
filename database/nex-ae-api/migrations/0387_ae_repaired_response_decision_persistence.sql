BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_repaired_response_decisions (
    repaired_response_decision_id TEXT PRIMARY KEY,
    decision_schema_version TEXT NOT NULL DEFAULT 'ae_repaired_response_decision.v1'
        CHECK (decision_schema_version = 'ae_repaired_response_decision.v1'),
    decision_request_id TEXT NOT NULL,
    decision_status TEXT NOT NULL
        CHECK (decision_status IN ('RECORDED')),
    decision_action TEXT NOT NULL
        CHECK (decision_action IN ('accept_repair', 'keep_original')),
    repaired_response_handoff_id TEXT NOT NULL,
    handoff_request_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    chat_document_id TEXT NOT NULL,
    interaction_id TEXT NOT NULL,
    parent_cx_generation_id TEXT NOT NULL,
    repair_cx_generation_id TEXT NOT NULL,
    selected_cx_generation_id TEXT NOT NULL,
    rejected_cx_generation_id TEXT NOT NULL,
    remediation_action_id TEXT NOT NULL,
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    actor_claims_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(actor_claims_ref) = 'object'),
    decision_reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(decision_reason_codes) = 'array'),
    decision_comment_hash TEXT NULL CHECK (
        decision_comment_hash IS NULL
        OR decision_comment_hash ~ '^[0-9a-f]{64}$'
    ),
    decision_comment_preview TEXT NULL CHECK (
        decision_comment_preview IS NULL
        OR length(decision_comment_preview) <= 240
    ),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (decision_action = 'accept_repair'
            AND selected_cx_generation_id = repair_cx_generation_id
            AND rejected_cx_generation_id = parent_cx_generation_id)
        OR
        (decision_action = 'keep_original'
            AND selected_cx_generation_id = parent_cx_generation_id
            AND rejected_cx_generation_id = repair_cx_generation_id)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ae_repaired_response_decisions_request
    ON ae_repaired_response_decisions (decision_request_id);

CREATE INDEX IF NOT EXISTS idx_ae_repaired_response_decisions_handoff_time
    ON ae_repaired_response_decisions
    (repaired_response_handoff_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_repaired_response_decisions_interaction_time
    ON ae_repaired_response_decisions (interaction_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_repaired_response_decisions_owner_time
    ON ae_repaired_response_decisions
    (tenant_id, workspace_id, owner_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_repaired_response_decisions_selected_generation
    ON ae_repaired_response_decisions (selected_cx_generation_id);

CREATE INDEX IF NOT EXISTS idx_ae_repaired_response_decisions_remediation_action
    ON ae_repaired_response_decisions (remediation_action_id);

INSERT INTO schema_migrations (version, description)
VALUES ('0387_ae_repaired_response_decision_persistence', 'AE repaired response decision persistence foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
