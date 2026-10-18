# P7-S5 - DELEGATE_WORK Compile, Executor, and Durable Wait

## Status

COMPLETED

## Implemented

- extended the P7 PlanCandidate and AgentPlan boundary with bounded
  `DELEGATE_WORK` metadata only: work class, required Agent type, project scope,
  result contract, and completion policy;
- preserved planning depth `1` and rejected claimant identity, routing,
  assignment, or claim authority in model-produced delegation metadata;
- compiled admitted delegation steps deterministically from logical `S-key` to
  executable `E-key` with `executor_kind=WC_DELEGATE_WORK`;
- derived stable child WorkItem and WaitRegistration identifiers from the
  parent execution and executable-step lineage;
- added the fail-closed `WC_DELEGATE_WORK` executor, authenticated WC client,
  and service-owned persistence adapters;
- generalized WC WorkItem creation to accept a caller-supplied stable UUID
  while preserving immutable idempotency checks;
- added durable `ae_wait_registration` persistence and PostgreSQL indexes for
  exact pending external-result lookup;
- made the first invocation converge through wait persistence, idempotent WC
  WorkItem creation, executable-step `WAITING`, and parent
  `WAITING_DEPENDENCY` transition;
- reused shared signed-token admission for the P7 AE internal APIs instead of
  maintaining a route-local authorization variant;
- admitted `nex-wc` into platform operations projection, production
  responsibility, vertical-spine, OpenAPI, and trace inventory checks exposed
  by the Checkpoint Gate.

## Boundary

AE owns the parent execution, executable step, and WaitRegistration. WC owns
the delegated WorkItem and all later routing, assignment, and claim authority.
The model may describe the requested work but cannot select a claimant or
create execution authority. S5 intentionally creates no terminal StepResult:
WorkResult ingestion, wait satisfaction, exactly-once `RESUME_EXECUTION`, and
parent continuation remain P7-S6 scope.

The durable ordering is retry-safe. A repeated step invocation resolves the
same child WorkItem and wait identifiers, verifies immutable data, and cannot
create a second semantic delegation. PostgreSQL timestamps are normalized to
UTC before retry comparison so database timezone presentation cannot create a
false immutable conflict.

## Migrations

- `2402_ae_wait_registration`: adds the durable wait system of record using
  the existing text executable-step identity and UUID parent execution
  identity;
- `2403_ae_delegate_work_activation`: admits plan schema `1.3`,
  `DELEGATE_WORK`, and `WC_DELEGATE_WORK` without weakening existing executor
  constraints.

## Verification

- focused P7-S5 tests and affected AE/WC regression: PASS;
- changed `delegated_work.py` coverage: statement/branch combined report `93%`;
- AE/WC Slice Gate: `4,488 passed`, `11 skipped`;
- AE/WC Slice Gate coverage: statement `98.29%`, branch `96.32%`;
- actual `nex_ae_test` and `nex_wc_test` migration, create/read/retry/wait
  transition, and cleanup smoke: PASS (`18/18`, waits `1`, WorkItems `1`,
  residue `0`);
- P7-S1 through P7-S5 Checkpoint Gate: `14,558 passed`, `38 skipped`;
- Checkpoint coverage: statement `98.92%`, branch `97.44%`;
- contract validation: PASS (`174` schemas, `236` examples, `204` negative
  examples, `8` OpenAPI documents).

## Checkpoint Findings Closed

- corrected the wait-to-step foreign-key type to match the existing text
  executable-step identity;
- removed database-rendered `created_at` from immutable retry identity and
  canonicalized PostgreSQL timestamps to UTC;
- replaced route-local internal authorization with the shared signed-token
  service admission boundary;
- updated platform-wide service inventories that still assumed only OA, AE,
  CX, MO, and AG after NeX-WC became an active service.

## Next

P7-S6 may add WorkResult ingestion, the durable event inbox, event-before-wait
and wait-before-event convergence, and exactly-once parent
`RESUME_EXECUTION` scheduling against the S5 WaitRegistration boundary.
