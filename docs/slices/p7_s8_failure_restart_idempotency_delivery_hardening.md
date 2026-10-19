# P7-S8: Failure / Restart / Idempotency / Delivery Hardening

## Status

Completed on 2026-10-19. P7-S9 is authorized.

## Goal

Prove that cross-service retries preserve semantic identity and do not create
duplicate WorkItems, active Claim generations, child AgentExecutions,
WorkResults, resume RuntimeJobs, or parent StepResults.

## Source Audit and Decisions

- WC already persisted Claim, Assignment, and handoff outbox state, but it did
  not reclaim an expired Claim. Reclaim now expires the old Claim, releases its
  Assignment, fails its pending/enqueued handoff, and allocates generation + 1
  in the same repository transaction.
- Handoff delivery now reloads and verifies the exact active Claim,
  Assignment, generation, and unexpired lease before crossing the AE boundary.
- AE already created a durable `RESUME_EXECUTION` RuntimeJob, but the multi-step
  engine rejected that job type. The existing worker now admits only the exact
  matched WorkResult event and consumes the wait atomically with StepResult.
- WC WorkResult publication used the retry attempt time as `submitted_at`.
  It now uses the immutable ResultDelivery creation time so a response-lost
  retry carries the same semantic hash.
- No schema migration or second queue/worker framework was required. WC and AE
  continue to reuse their existing service-owned records and runtime queues.

## Failure Matrix

New S8 fault injection proves:

```text
Claim lease expiry                    -> generation 1 EXPIRED, generation 2 ACTIVE
Stale handoff after reclaim           -> fail closed before AE invocation
Handoff ACK loss / replay             -> one child CLAIMED_WORKITEM execution
WorkResult response loss / replay     -> stable payload and one WC WorkResult
Result event ACK loss / replay        -> one inbox row and one resume job
Resume crash after StepResult commit  -> lease recovery and one StepResult
Corrupt or timezone-less lease        -> typed fail-closed rejection
```

The existing P6/P6.5/P7 regression suites continue to cover WC, AE, and OA
unavailability; MO timeout/429/5xx; child worker restart; NSL timeout/crash;
result-submit timeout; and cancellation of a parent before event admission.
S8 preserves those tests and adds the missing cross-service recovery paths.

## PostgreSQL Evidence

The protected runner used the actual local `nex_ae_test` and `nex_wc_test`
databases and applied the current migration inventories before mutation.

```text
AE migration latest       = 2405_ae_claimed_planning_source
WC migration latest       = 1002_wc_work_result
Claim rows                 = 2 (EXPIRED, ACTIVE)
WC WorkResult rows         = 1
AE WorkResult inbox rows   = 1
AE resume RuntimeJobs      = 1
AE resume attempts         = 2 (LEASE_EXPIRED, DONE)
Parent StepResults         = 1
checks                     = 26 / 26
owned residue              = 0
```

Remote generation was intentionally not called. Provider failure behavior is
deterministic mock regression in S8; P7-S9 remains the protected PostgreSQL,
OA, live MO generation, and admitted NSL Golden B acceptance.

Sanitized evidence is stored in
`reports/live/p7-s8-failure-restart-postgres.json`.

## Verification

- Focused S8 resilience and runner tests: PASS.
- Actual AE/WC PostgreSQL failure smoke: PASS, `26/26`, zero owned residue.
- WC Slice Gate with protected PostgreSQL tests: `166 passed`; statement
  `96.74%`; branch `94.12%`.
- AE Slice Gate: `4499 passed`, `15 skipped` protected tests; statement
  `98.29%`; branch `96.14%`.
- New `work_result_resume` boundary: statement and branch `100%`.
- Contract validation: schemas `174`, examples `236`, negative examples `204`,
  OpenAPI documents `8`.
- Ruff and `git diff --check`: PASS.

The default WC service profile does not automatically discover joint-owner
`test_ae_wc_p7_*` files. The authoritative P7 WC Gate therefore lists that
inventory explicitly; protected PostgreSQL coverage also requires the AE and
WC test database URLs. The ordinary AE Gate keeps protected smokes opt-in.
