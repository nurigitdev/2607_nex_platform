BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_repaired_response_handoffs (
    repaired_response_handoff_id TEXT PRIMARY KEY,
    handoff_schema_version TEXT NOT NULL DEFAULT 'ae_repaired_response_handoff.v1'
        CHECK (handoff_schema_version = 'ae_repaired_response_handoff.v1'),
    handoff_request_id TEXT NOT NULL,
    handoff_status TEXT NOT NULL
        CHECK (handoff_status IN ('READY_FOR_USER_REVIEW')),
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    chat_document_id TEXT NOT NULL,
    interaction_id TEXT NOT NULL,
    original_cx_generation_id TEXT NOT NULL,
    parent_cx_generation_id TEXT NOT NULL,
    root_cx_generation_id TEXT NOT NULL,
    repair_cx_generation_id TEXT NOT NULL,
    remediation_action_id TEXT NOT NULL,
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    actor_claims_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(actor_claims_ref) = 'object'),
    source JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(source) = 'object'),
    repaired_response JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(repaired_response) = 'object'),
    lineage JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(lineage) = 'object'),
    user_surface JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(user_surface) = 'object'),
    links JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(links) = 'object'),
    redaction_summary JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(redaction_summary) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ae_repaired_response_handoffs_request
    ON ae_repaired_response_handoffs (handoff_request_id);

CREATE INDEX IF NOT EXISTS idx_ae_repaired_response_handoffs_owner_time
    ON ae_repaired_response_handoffs
    (tenant_id, workspace_id, owner_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_repaired_response_handoffs_interaction_time
    ON ae_repaired_response_handoffs (interaction_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_repaired_response_handoffs_parent_generation
    ON ae_repaired_response_handoffs (parent_cx_generation_id);

CREATE INDEX IF NOT EXISTS idx_ae_repaired_response_handoffs_repair_generation
    ON ae_repaired_response_handoffs (repair_cx_generation_id);

CREATE INDEX IF NOT EXISTS idx_ae_repaired_response_handoffs_remediation_action
    ON ae_repaired_response_handoffs (remediation_action_id);

INSERT INTO schema_migrations (version, description)
VALUES ('0383_ae_repaired_response_handoff_persistence', 'AE repaired response handoff persistence foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
