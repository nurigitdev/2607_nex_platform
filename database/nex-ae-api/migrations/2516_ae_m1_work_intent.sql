BEGIN;

ALTER TABLE ae_work_intent
    DROP CONSTRAINT IF EXISTS ae_work_intent_work_class_check;

ALTER TABLE ae_work_intent
    ADD CONSTRAINT ae_work_intent_work_class_check CHECK (
        work_class IN (
            'QUERY', 'ANALYSIS', 'DOCUMENT', 'REPORTING',
            'BUSINESS_TRANSACTION'
        )
    );

ALTER TABLE ae_work_intent
    DROP CONSTRAINT IF EXISTS ck_ae_work_intent_json_identity;

ALTER TABLE ae_work_intent
    ADD CONSTRAINT ck_ae_work_intent_json_identity CHECK (
        intent_json ->> 'schema_version' IN ('1.1', '1.2')
        AND intent_json ->> 'work_intent_id' = work_intent_id::text
        AND intent_json ->> 'execution_id' = agent_execution_id::text
        AND (intent_json ->> 'intent_revision')::integer = intent_revision
        AND intent_json ->> 'intent_hash' = intent_hash
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2516_ae_m1_work_intent',
    'Admit durable M1 business transaction WorkIntent schema 1.2'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
