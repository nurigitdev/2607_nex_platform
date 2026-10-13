BEGIN;

ALTER TABLE ae_executable_step
    DROP CONSTRAINT IF EXISTS ae_executable_step_step_kind_check;

ALTER TABLE ae_executable_step
    DROP CONSTRAINT IF EXISTS ux_ae_step_execution_kind;

ALTER TABLE ae_executable_step
    ADD COLUMN IF NOT EXISTS executable_plan_id UUID NULL,
    ADD COLUMN IF NOT EXISTS logical_step_id TEXT NULL,
    ADD COLUMN IF NOT EXISTS compiled_step_key TEXT NULL,
    ADD COLUMN IF NOT EXISTS step_index INTEGER NULL,
    ADD COLUMN IF NOT EXISTS step_type TEXT NULL,
    ADD COLUMN IF NOT EXISTS executor_kind TEXT NULL,
    ADD COLUMN IF NOT EXISTS required_capability TEXT NULL,
    ADD COLUMN IF NOT EXISTS capability_version TEXT NULL,
    ADD COLUMN IF NOT EXISTS dependency_json JSONB NULL,
    ADD COLUMN IF NOT EXISTS input_binding_json JSONB NULL,
    ADD COLUMN IF NOT EXISTS output_contract_ref TEXT NULL,
    ADD COLUMN IF NOT EXISTS step_contract_hash TEXT NULL;

ALTER TABLE ae_executable_step
    ADD CONSTRAINT ck_ae_step_kind CHECK (
        step_kind IN (
            'P4_CHAT_RAG_COMPATIBILITY',
            'DETERMINISTIC_AGGREGATE',
            'DETERMINISTIC_REPORT',
            'LOCAL_SKILL_UNAVAILABLE',
            'DELEGATE_WORK_UNAVAILABLE'
        )
    ),
    ADD CONSTRAINT fk_ae_step_plan
        FOREIGN KEY (tenant_id, executable_plan_id)
        REFERENCES ae_executable_plan (tenant_id, executable_plan_id),
    ADD CONSTRAINT ux_ae_step_plan_key
        UNIQUE (tenant_id, executable_plan_id, compiled_step_key),
    ADD CONSTRAINT ck_ae_step_p5_shape CHECK (
        (
            executable_plan_id IS NULL
            AND logical_step_id IS NULL
            AND compiled_step_key IS NULL
            AND step_index IS NULL
            AND step_type IS NULL
            AND executor_kind IS NULL
            AND required_capability IS NULL
            AND capability_version IS NULL
            AND dependency_json IS NULL
            AND input_binding_json IS NULL
            AND output_contract_ref IS NULL
            AND step_contract_hash IS NULL
        )
        OR
        (
            executable_plan_id IS NOT NULL
            AND logical_step_id ~ '^S[0-9]{1,3}$'
            AND compiled_step_key ~ '^E[0-9]{1,3}$'
            AND step_index BETWEEN 0 AND 23
            AND step_type IS NOT NULL
            AND executor_kind = step_kind
            AND jsonb_typeof(dependency_json) = 'array'
            AND jsonb_typeof(input_binding_json) = 'array'
            AND output_contract_ref IS NOT NULL
            AND step_contract_hash ~ '^sha256:[0-9a-f]{64}$'
        )
    );

CREATE INDEX IF NOT EXISTS idx_ae_step_plan_order
    ON ae_executable_step (tenant_id, executable_plan_id, step_index)
    WHERE executable_plan_id IS NOT NULL;

INSERT INTO schema_migrations (version, description)
VALUES (
    '2105_ae_executable_step_generalization',
    'P5 multi-step S-key E-key UUID lineage while retaining historical P4 rows'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
