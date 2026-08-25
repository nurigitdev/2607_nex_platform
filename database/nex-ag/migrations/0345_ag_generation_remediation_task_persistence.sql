BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ag_generation_remediation_tasks (
    remediation_action_id TEXT PRIMARY KEY,
    action_schema_version TEXT NOT NULL DEFAULT 'ag_generation_remediation_action.v1'
        CHECK (action_schema_version = 'ag_generation_remediation_action.v1'),
    cx_generation_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    trace_id TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    action_type TEXT NOT NULL CHECK (
        action_type IN (
            'retry_generation',
            'retrieval_repair',
            'citation_repair',
            'prompt_policy_review',
            'operator_followup',
            'mark_accepted'
        )
    ),
    action_status TEXT NOT NULL CHECK (
        action_status IN (
            'PROPOSED',
            'ASSIGNED',
            'IN_PROGRESS',
            'WAITING_ON_CX',
            'COMPLETED',
            'FAILED',
            'CANCELLED'
        )
    ),
    priority TEXT NOT NULL CHECK (priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')),
    owner_type TEXT NOT NULL CHECK (owner_type IN ('service', 'user')),
    owner_id TEXT NOT NULL,
    owner_tenant_id TEXT,
    owner_ref JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(owner_ref) = 'object'),
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(reason_codes) = 'array'),
    source_refs JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(source_refs) = 'array'),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(evidence) = 'object'),
    result_ref JSONB DEFAULT NULL
        CHECK (result_ref IS NULL OR jsonb_typeof(result_ref) = 'object'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ag_generation_remediation_tasks_generation_time
    ON ag_generation_remediation_tasks (cx_generation_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_generation_remediation_tasks_status_time
    ON ag_generation_remediation_tasks (action_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_generation_remediation_tasks_type_time
    ON ag_generation_remediation_tasks (action_type, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ag_generation_remediation_tasks_owner_time
    ON ag_generation_remediation_tasks (owner_type, owner_id, updated_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('0345_ag_generation_remediation_task_persistence', 'AG generation remediation task persistence foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
