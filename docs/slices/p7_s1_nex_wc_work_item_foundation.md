# P7-S1 - NeX-WC Service and WorkItem Foundation

## Status

COMPLETED

## Implemented

- registered `nex-wc` as the sixth bounded backend service on port `8106`;
- added `NEX_WC_DATABASE_URL` and `NEX_WC_TEST_DATABASE_URL` migration profiles;
- reused service-local `nex_runtime.JobQueue`, operational events, service logs,
  and worker heartbeat persistence without creating a second common queue;
- added `wc_work_item`, `wc_routing_decision`, and `wc_event_outbox` foundations;
- implemented server-owned WorkItem creation from validated P7 DelegationSpec;
- derived idempotency through `nex_runtime.semantic_hashes`;
- implemented protected create, read, and status APIs with tenant-scoped reads;
- added the WC OpenAPI contract and development/quality-gate inventory.

## Boundary

`service_jobs` is WC-local technical work storage. `wc_work_item`, routing, and
outbox records remain WC domain systems of record. P7-S1 does not route, claim,
assign, or start an AgentExecution.

## Verification

- focused unit/API tests: `28 passed`;
- protected PostgreSQL test: `1 passed` against `nex_wc_test`;
- migration: seven WC migrations applied successfully;
- PostgreSQL evidence: idempotent insert, select after repository restart,
  semantic conflict, cleanup, and zero residue;
- WC Slice Gate: `29 passed`;
- statement coverage: `98.84%`;
- branch coverage: `95.59%`;
- contract validation: `174 schemas`, `236 examples`, `204 negative examples`,
  `8 OpenAPI documents`, PASS;
- shared app/database/migration/dev/quality regression: `125 passed`.

## Next

P7-S2 may activate the existing AE `ae_agent_identity` table for CA/PA/EA
registry operations and WC-protected metadata reads.
