BEGIN;

CREATE TABLE IF NOT EXISTS ae_wait_registration (
    wait_id UUID NOT NULL,
    tenant_id TEXT NOT NULL,
    agent_execution_id UUID NOT NULL,
    executable_step_id TEXT NOT NULL,
    wait_type TEXT NOT NULL CHECK (wait_type = 'WORK_RESULT'),
    external_ref UUID NOT NULL,
    result_contract_ref TEXT NOT NULL,
    state TEXT NOT NULL
        CHECK (state IN ('PENDING', 'SATISFIED', 'RESUME_QUEUED', 'CONSUMED', 'CANCELLED')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TIMESTAMPTZ NOT NULL,
    satisfied_at TIMESTAMPTZ NULL,
    PRIMARY KEY (tenant_id, wait_id),
    CONSTRAINT ux_ae_wait_step_type UNIQUE (
        tenant_id, agent_execution_id, executable_step_id, wait_type
    ),
    CONSTRAINT fk_ae_wait_execution FOREIGN KEY (tenant_id, agent_execution_id)
        REFERENCES ae_agent_execution (tenant_id, agent_execution_id),
    CONSTRAINT fk_ae_wait_step FOREIGN KEY (tenant_id, executable_step_id)
        REFERENCES ae_executable_step (tenant_id, executable_step_id),
    CONSTRAINT ck_ae_wait_satisfied_at CHECK (
        (state = 'PENDING' AND satisfied_at IS NULL)
        OR state IN ('SATISFIED', 'RESUME_QUEUED', 'CONSUMED', 'CANCELLED')
    )
);

CREATE INDEX IF NOT EXISTS ix_ae_wait_external_pending
    ON ae_wait_registration (tenant_id, external_ref, wait_type)
    WHERE state = 'PENDING';

INSERT INTO schema_migrations (version, description)
VALUES (
    '2402_ae_wait_registration',
    'AE durable delegated WorkItem wait registration foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
