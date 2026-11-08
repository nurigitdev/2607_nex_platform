-- NeX-WC WorkResult / dependency resume v2.1 — Step2 E2E Contract Hardening
BEGIN;

-- Lock tenant-scoped WorkItem and validate current assignment/claim ownership.
SELECT * FROM nex_wc.work_item
 WHERE tenant_id=:tenant_id AND work_item_id=:work_item_id
 FOR UPDATE;

-- For AGENT submission, application MUST validate:
-- claimant_agent_ref/current assignment, claim_ref, claim_generation, lease/ownership,
-- result schema contract, current OA authorization, and idempotency.

INSERT INTO nex_wc.work_result(
    tenant_id, result_id, work_item_id, revision_no, result_type, summary,
    schema_ref, payload_json, technical_outcome, business_outcome,
    artifact_refs, evidence_refs, business_object_refs,
    source_execution_ref, source_plan_ref, claim_ref, claim_generation, assignment_ref,
    submitted_by_type, submitted_by_ref, correlation_id, causation_id, idempotency_key
) VALUES (
    :tenant_id, :result_id, :work_item_id, :revision_no, :result_type, :summary,
    :schema_ref, :payload_json::jsonb, :technical_outcome, :business_outcome,
    :artifact_refs::jsonb, :evidence_refs::jsonb, :business_object_refs::jsonb,
    :source_execution_ref, :source_plan_ref, :claim_ref, :claim_generation, :assignment_ref,
    :submitted_by_type, :submitted_by_ref, :correlation_id, :causation_id, :idempotency_key
);

UPDATE nex_wc.work_item
 SET state='RESULT_SUBMITTED', version=version+1, updated_at=now()
 WHERE tenant_id=:tenant_id AND work_item_id=:work_item_id AND version=:expected_version;

INSERT INTO nex_wc.event_outbox(
    outbox_id, event_id, event_name, aggregate_ref, payload_json, correlation_id, causation_id
) VALUES (
    :outbox_id, :event_id, 'WORK_RESULT_SUBMITTED',
    'WORKITEM:' || :work_item_id,
    jsonb_build_object(
      'schema_version','2.1', 'event_id',:event_id, 'event_name','WORK_RESULT_SUBMITTED',
      'tenant_id',:tenant_id, 'work_item_id',:work_item_id, 'result_id',:result_id,
      'revision_no',:revision_no, 'result_type',:result_type, 'result_schema_ref',:schema_ref,
      'technical_outcome',:technical_outcome, 'business_outcome',:business_outcome,
      'source_execution_ref',:source_execution_ref, 'claim_ref',:claim_ref,
      'claim_generation',:claim_generation, 'assignment_ref',:assignment_ref,
      'submitted_by',jsonb_build_object('entity_type',:submitted_by_type,'entity_id',:submitted_by_ref),
      'resume_match_ref',:work_item_id, 'correlation_id',:correlation_id,
      'causation_id',:causation_id, 'occurred_at',now()
    ), :correlation_id, :causation_id
);

COMMIT;

-- AE consumes event_id idempotently, matches wait_condition.external_ref = resume_match_ref,
-- validates result schema/business contract, reauthorizes, then enqueues one Resume RuntimeJob.
-- WC never writes AE AgentExecution state directly.
