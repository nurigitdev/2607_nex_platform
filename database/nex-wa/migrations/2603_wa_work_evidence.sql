BEGIN;

CREATE TABLE IF NOT EXISTS wa_work_evidence (
    tenant_id TEXT NOT NULL,
    work_evidence_id UUID NOT NULL,
    source_owner TEXT NOT NULL,
    source_type TEXT NOT NULL
        CHECK (source_type IN ('AE_AGENT_RESULT', 'AE_ARTIFACT', 'WC_WORK_RESULT')),
    source_ref TEXT NOT NULL,
    source_revision_ref TEXT NOT NULL,
    source_hash TEXT NOT NULL
        CHECK (source_hash ~ '^sha256:[0-9a-f]{64}$'),
    evidence_kind TEXT NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('HUMAN', 'AGENT')),
    actor_ref TEXT NOT NULL,
    agent_type_snapshot TEXT
        CHECK (
            agent_type_snapshot IS NULL
            OR agent_type_snapshot IN ('IA', 'CA', 'PA', 'EA')
        ),
    project_ref UUID,
    occurred_at TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    classification TEXT NOT NULL
        CHECK (classification IN ('INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')),
    evidence_status TEXT NOT NULL
        CHECK (evidence_status IN ('ACTIVE', 'SUPERSEDED', 'INVALIDATED')),
    evidence_hash TEXT NOT NULL
        CHECK (evidence_hash ~ '^sha256:[0-9a-f]{64}$'),
    supersedes_evidence_id UUID,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, work_evidence_id),
    CONSTRAINT ux_wa_work_evidence_source
        UNIQUE (tenant_id, source_type, source_ref, source_revision_ref),
    CONSTRAINT ck_wa_work_evidence_not_self_superseding
        CHECK (
            supersedes_evidence_id IS NULL
            OR supersedes_evidence_id <> work_evidence_id
        ),
    CONSTRAINT fk_wa_work_evidence_supersedes
        FOREIGN KEY (tenant_id, supersedes_evidence_id)
        REFERENCES wa_work_evidence (tenant_id, work_evidence_id)
);

CREATE INDEX IF NOT EXISTS ix_wa_work_evidence_project_occurred
    ON wa_work_evidence (tenant_id, project_ref, occurred_at DESC)
    WHERE project_ref IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_wa_work_evidence_actor_occurred
    ON wa_work_evidence (tenant_id, actor_type, actor_ref, occurred_at DESC);

CREATE INDEX IF NOT EXISTS ix_wa_work_evidence_status
    ON wa_work_evidence (tenant_id, evidence_status, occurred_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('2603_wa_work_evidence', 'WA immutable WorkEvidence persistence')
ON CONFLICT (version) DO NOTHING;

COMMIT;
