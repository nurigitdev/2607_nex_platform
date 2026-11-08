# P7-S3 - WC Deterministic Routing and Atomic Claim

## Status

COMPLETED

## Implemented

- added deterministic, model-independent routing against bounded AE Agent
  Registry projections;
- activated the initial exact policy mapping
  `FINANCE.PROJECT_BUDGET_CHECK` to
  `agent-profile://pa/project-budget-read/v1`;
- persisted versioned routing decisions and candidate reason codes without
  treating discovery as execution authority;
- added atomic Assignment, Claim, lease verifier, WorkItem transition, and
  `CLAIM_EXECUTION_HANDOFF` outbox persistence;
- revalidated the selected AE Agent and fresh OA `work:claim` authorization at
  claim time;
- returned the raw lease token only once while persisting its semantic SHA-256
  verifier;
- exposed protected route/claim APIs and fail-closed AE/OA HTTP source clients;
- kept routing policy, claim authority, and WC persistence independent of any
  generation model.

## Boundary

Routing selects an eligible Agent but does not authorize execution. A committed
Claim is the authority boundary. WC owns Assignment, Claim, lease, and handoff
outbox state; AE and OA remain authoritative for Agent metadata and current
authorization respectively. S3 does not deliver the handoff or admit an AE
`CLAIMED_WORKITEM` execution.

## Verification

- focused S3 unit and actual PostgreSQL smoke: `25 passed`;
- changed-module statement/branch coverage: `99%`;
- actual `nex_wc_test` migration `1001_wc_assignment_claim` applied;
- PostgreSQL atomic claim, restart read, conflict guards, lease-secret absence,
  cleanup, and zero residue PASS;
- P7 S1-S3 regression with actual WC/AE PostgreSQL tests: `68 passed`;
- contract validation: PASS (`174` schemas, `236` examples, `204` negative
  examples, `8` OpenAPI documents).

## Next

P7-S4 may bridge the durable WC handoff outbox through the shared technical
JobQueue and admit exactly one AE `CLAIMED_WORKITEM` AgentExecution.
