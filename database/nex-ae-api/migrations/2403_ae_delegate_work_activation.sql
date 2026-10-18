BEGIN;

ALTER TABLE ae_executable_plan
    DROP CONSTRAINT IF EXISTS ck_ae_exec_plan_json_id;

ALTER TABLE ae_executable_plan
    ADD CONSTRAINT ck_ae_exec_plan_json_id CHECK (
        plan_json ->> 'schema_version' IN ('1.1', '1.2', '1.3')
        AND plan_json ->> 'executable_plan_id' = executable_plan_id::text
        AND (plan_json ->> 'executable_plan_version')::integer = executable_plan_version
        AND plan_json ->> 'execution_id' = agent_execution_id::text
        AND plan_json ->> 'executable_plan_hash' = plan_hash
    );

ALTER TABLE ae_executable_step
    DROP CONSTRAINT IF EXISTS ck_ae_step_kind,
    DROP CONSTRAINT IF EXISTS ck_ae_step_p5_shape;

ALTER TABLE ae_executable_step
    ADD CONSTRAINT ck_ae_step_kind CHECK (
        step_kind IN (
            'P4_CHAT_RAG_COMPATIBILITY',
            'DETERMINISTIC_AGGREGATE',
            'DETERMINISTIC_REPORT',
            'LOCAL_SKILL',
            'LOCAL_SKILL_UNAVAILABLE',
            'DELEGATE_WORK_UNAVAILABLE',
            'WC_DELEGATE_WORK'
        )
    ),
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
            AND skill_binding_json IS NULL
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
            AND (
                (executor_kind = 'LOCAL_SKILL'
                    AND step_type = 'LOCAL_SKILL'
                    AND jsonb_typeof(skill_binding_json) = 'object')
                OR
                (executor_kind <> 'LOCAL_SKILL' AND skill_binding_json IS NULL)
            )
            AND (
                executor_kind <> 'WC_DELEGATE_WORK'
                OR step_type = 'DELEGATE_WORK'
            )
            AND output_contract_ref IS NOT NULL
            AND step_contract_hash ~ '^sha256:[0-9a-f]{64}$'
        )
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2403_ae_delegate_work_activation',
    'P7 deterministic DELEGATE_WORK compiler and WC executor activation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
