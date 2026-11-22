BEGIN;

CREATE TABLE IF NOT EXISTS eos_project_app_approval (
    tenant_id VARCHAR(128) NOT NULL,
    application_id UUID NOT NULL,
    approval_policy_id UUID NOT NULL,
    policy_version INTEGER NOT NULL,
    policy_hash VARCHAR(71) NOT NULL,
    approval_hash VARCHAR(71) NOT NULL,
    requester_subject_id VARCHAR(128) NOT NULL,
    state VARCHAR(16) NOT NULL,
    active_stage_order INTEGER NULL,
    stage_count INTEGER NOT NULL,
    target_role_ref VARCHAR(32) NULL,
    version INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    decided_at TIMESTAMPTZ NULL,
    CONSTRAINT pk_eos_project_app_approval PRIMARY KEY (
        tenant_id, application_id
    ),
    CONSTRAINT fk_eos_project_app_approval_application FOREIGN KEY (
        tenant_id, application_id
    ) REFERENCES eos_project_application (tenant_id, application_id),
    CONSTRAINT fk_eos_project_app_approval_policy FOREIGN KEY (
        tenant_id, approval_policy_id
    ) REFERENCES eos_approval_policy (tenant_id, approval_policy_id),
    CONSTRAINT ck_eos_project_app_approval_state CHECK (
        state IN ('PENDING', 'APPROVED', 'REJECTED')
    ),
    CONSTRAINT ck_eos_project_app_approval_stage_count CHECK (
        stage_count BETWEEN 1 AND 5
    ),
    CONSTRAINT ck_eos_project_app_approval_version CHECK (version > 0),
    CONSTRAINT ck_eos_project_app_approval_lifecycle CHECK (
        (
            state = 'PENDING'
            AND active_stage_order BETWEEN 1 AND stage_count
            AND target_role_ref IS NOT NULL
            AND decided_at IS NULL
        ) OR (
            state IN ('APPROVED', 'REJECTED')
            AND active_stage_order IS NULL
            AND target_role_ref IS NULL
            AND decided_at IS NOT NULL
        )
    ),
    CONSTRAINT ck_eos_project_app_approval_hashes CHECK (
        policy_hash ~ '^sha256:[0-9a-f]{64}$'
        AND approval_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_project_app_approval_state
    ON eos_project_app_approval (
        tenant_id, state, active_stage_order, updated_at
    );

CREATE TABLE IF NOT EXISTS eos_project_app_decision (
    tenant_id VARCHAR(128) NOT NULL,
    application_id UUID NOT NULL,
    stage_order INTEGER NOT NULL,
    wc_work_item_id UUID NOT NULL,
    wc_decision_id UUID NOT NULL,
    wc_event_id UUID NOT NULL,
    wc_outbox_id UUID NOT NULL,
    decision VARCHAR(16) NOT NULL,
    decision_version INTEGER NOT NULL,
    decided_by VARCHAR(128) NOT NULL,
    decision_comment TEXT NULL,
    wc_oa_decision_ref VARCHAR(128) NOT NULL,
    wc_authorization_revision_hash VARCHAR(71) NOT NULL,
    oa_decision_ref VARCHAR(128) NOT NULL,
    authorization_revision_hash VARCHAR(71) NOT NULL,
    authorization_checked_at TIMESTAMPTZ NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    decision_hash VARCHAR(71) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_project_app_decision PRIMARY KEY (
        tenant_id, application_id, stage_order
    ),
    CONSTRAINT fk_eos_project_app_decision_approval FOREIGN KEY (
        tenant_id, application_id
    ) REFERENCES eos_project_app_approval (tenant_id, application_id),
    CONSTRAINT ux_eos_project_app_decision_work_item UNIQUE (
        tenant_id, wc_work_item_id
    ),
    CONSTRAINT ux_eos_project_app_decision_decision UNIQUE (
        tenant_id, wc_decision_id
    ),
    CONSTRAINT ux_eos_project_app_decision_event UNIQUE (
        tenant_id, wc_event_id
    ),
    CONSTRAINT ux_eos_project_app_decision_hash UNIQUE (
        tenant_id, decision_hash
    ),
    CONSTRAINT ck_eos_project_app_decision_action CHECK (
        decision IN ('APPROVE', 'REJECT')
    ),
    CONSTRAINT ck_eos_project_app_decision_stage CHECK (
        stage_order BETWEEN 1 AND 5
    ),
    CONSTRAINT ck_eos_project_app_decision_version CHECK (
        decision_version = 1
    ),
    CONSTRAINT ck_eos_project_app_decision_hashes CHECK (
        wc_authorization_revision_hash ~ '^sha256:[0-9a-f]{64}$'
        AND authorization_revision_hash ~ '^sha256:[0-9a-f]{64}$'
        AND decision_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE OR REPLACE FUNCTION eos_guard_project_app_decision_immutable()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Project application approval decisions are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_eos_project_app_decision_immutable
BEFORE UPDATE OR DELETE ON eos_project_app_decision
FOR EACH ROW EXECUTE FUNCTION eos_guard_project_app_decision_immutable();

CREATE OR REPLACE FUNCTION eos_guard_project_app_approval_lifecycle()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.application_id IS DISTINCT FROM OLD.application_id
       OR NEW.approval_policy_id IS DISTINCT FROM OLD.approval_policy_id
       OR NEW.policy_version IS DISTINCT FROM OLD.policy_version
       OR NEW.policy_hash IS DISTINCT FROM OLD.policy_hash
       OR NEW.approval_hash IS DISTINCT FROM OLD.approval_hash
       OR NEW.requester_subject_id IS DISTINCT FROM OLD.requester_subject_id
       OR NEW.stage_count IS DISTINCT FROM OLD.stage_count
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'Project application approval identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'Project application approval version must advance by one'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.state <> 'PENDING' THEN
        RAISE EXCEPTION 'Terminal Project application approval is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.state = 'PENDING'
       AND NEW.active_stage_order <> OLD.active_stage_order + 1 THEN
        RAISE EXCEPTION 'Project committee stage must advance by one'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.state NOT IN ('PENDING', 'APPROVED', 'REJECTED') THEN
        RAISE EXCEPTION 'Project application approval transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_eos_project_app_approval_lifecycle
BEFORE UPDATE ON eos_project_app_approval
FOR EACH ROW EXECUTE FUNCTION eos_guard_project_app_approval_lifecycle();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2532_eos_project_application_approval',
    'Project committee approval, immutable decisions, and final Project materialization'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
