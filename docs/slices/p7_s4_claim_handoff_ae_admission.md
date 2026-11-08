# P7-S4 - Claim Handoff and AE Claimed-Work Admission

## Status

COMPLETED

## Implemented

- bridged committed `CLAIM_EXECUTION_HANDOFF` outbox rows into the WC
  service-local common JobQueue as `WC_EVENT_DELIVERY`;
- kept common job payloads reference-only with exactly `outbox_id` and
  `event_id`;
- added a shared WorkerRunner-based delivery worker and authenticated AE HTTP
  client;
- added the protected AE `/internal/v1/work-handoffs` endpoint restricted to
  `nex-wc` service authority;
- generalized `ae_agent_execution` historically safely for CA/PA/EA
  `CLAIMED_WORKITEM` triggers;
- added separate `admit_claimed_work()` service/repository paths without
  weakening the existing IA/PROMPT admission path;
- added `ae_claim_handoff_inbox` insert-or-verify evidence and atomic child
  AgentExecution admission;
- enforced exact active tenant/project/type Agent identity, complete
  Claim/Assignment generation lineage, handoff idempotency, and semantic
  conflict rejection;
- preserved the Frozen handoff payload: the technical delivery envelope derives
  `requester_ref` from the WC WorkItem because the canonical handoff schema does
  not carry that AE persistence field;
- admitted `nex-wc` to shared worker heartbeat and service-log ownership lists.

## Boundary

WC remains the outbox and Claim authority. The common JobQueue owns only
technical delivery/retry state. AE owns the inbox and AgentExecution. A
WorkItem or RoutingDecision cannot directly create an AgentExecution; only the
committed Claim handoff path can do so. Remote model providers are not involved
in S4.

## Verification

- focused S3/S4 and existing AgentExecution tests: `53 passed`;
- changed-module statement/branch coverage: `98%`;
- actual `nex_ae_test` migration `2401_ae_claimed_work_execution` applied;
- actual `nex_wc_test` JobQueue to `nex_ae_test` child execution smoke: PASS;
- PostgreSQL restart reads, duplicate admission, delivery state, cleanup, and
  zero residue: PASS;
- P7 S1-S4 plus shared worker/log regression: `167 passed`;
- shared worker heartbeat/service-log regression: `71 passed`;
- contract validation: PASS (`174` schemas, `236` examples, `204` negative
  examples, `8` OpenAPI documents).

## Next

P7-S5 may activate provider-free `DELEGATE_WORK` compile/execution and durable
parent wait registration, using the S4 handoff path as the only child execution
authority.
