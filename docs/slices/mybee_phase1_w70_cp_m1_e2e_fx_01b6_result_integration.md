# CP-M1-E2E-FX-01B.6 Allocation, P&L, WA, and IA Result Integration

## Status

- Date: `2026-11-17`
- Status: `CLOSED`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_Durable_Business_Context_and_M1_Transaction_Orchestration_Closure_v1.0.md`
- Corrective predecessor: `CP-M1-E2E-FX-01B.6A.3`
- Database migration: none
- Remote provider: not required
- Successor: `CP-M1-E2E-FX-01B.7`

This Slice connects the verified D04 Posted Journal result to the existing EOS
allocation and Project P&L product APIs, then closes the PA result through the
existing AE, WC, WA, and owner-visible IA publication boundaries. It introduces
no M1-specific persistence, direct EOS SQL, fixed Plan ID, fixed ratio, tenant
dictionary, or fallback selection.

## Product Flow

The installed runtime now owns only this authority-preserving sequence:

```text
verified PostedJournal
  -> FINANCE.COST_SOURCE_POOL.ADMIT
  -> FINANCE.COST_ALLOCATION.RUN
  -> FINANCE.COST_ALLOCATION.VERIFY
  -> FINANCE.PROJECT_PNL.REFRESH_FROM_ALLOCATION(batch_id)
  -> FINANCE.PROJECT_PNL.GET for each admitted Project
  -> redacted PA AgentResult and WC WorkResult
  -> WC publication ACK
  -> WA evidence-intake notification
  -> owner-visible IA result publication
```

The MyBee preparation registry declares only generic source-pool policy:
`SHARED_EXPENSE`, `MANAGEMENT_ALLOCATION`, and a source line reference. EOS
still owns journal eligibility, SourcePool admission, allocation mutation,
verification, Project P&L projection, replay, and reconciliation.

`M1FinancialResultIntegrator` accepts the committed Journal identity and the
durable preparation checkpoint. It calls the generic EOS consumers, requires
the exact admitted allocation authority, requires conservation and a verified
Batch, refreshes by Batch ID only, and reads only the exact Project projections
returned by EOS. Current OA-backed subject authorization remains mandatory on
every Project P&L read.

## Durable Runtime and Result Closure

The D04 technical checkpoint is now persisted in compiled inputs. It is removed
before the canonical NSL/EOS business payload is hashed, so it cannot change the
approved write semantics, but remains available after commit for deterministic
allocation and result integration.

The installed AE runtime now:

- joins AgentContext to its exact WorkIntent and execution correlation;
- enriches only a successful, verified controlled-WRITE outcome;
- stores the private financial result in StepResult lineage;
- publishes only a redacted Project allocation summary to AgentResult and
  WorkResult;
- resumes PA/CA/EA executions from `RESULT_VERIFY` or `RESULT_PUBLISH` after a
  restart;
- reuses the existing P5 finalizer, WC publisher, AgentResult source projection,
  WA completion notifier, and IA workspace publisher; and
- requires signed AE-to-WC and AE-to-WA trust in staging and production.

The public summary carries Journal, SourcePool, AllocationBatch,
reconciliation, refresh, and Project projection identities only. It excludes
P&L amounts, component detail, payroll detail, private source content, and
cross-Project aggregates.

## Reliability and Fail-Closed Rules

- exact replay returns the same authoritative Journal, Batch, projection, and
  delivery identities;
- a changed payload, source hash, Plan authority, Project set, or projection
  identity fails closed;
- an unverified Batch, nonzero unallocated amount, conservation mismatch, or
  unauthorized Project read cannot produce a success result;
- `RESULT_PUBLISH` restart resumes the existing delivery rather than creating
  another AgentResult or WorkResult;
- WC ACK loss remains retryable through the persisted delivery;
- WA admission is post-completion and idempotent by source identity; and
- a notification failure does not roll back the already authoritative Agent
  result, but remains observable and retryable.

## Verification

- Focused allocation, P&L, runtime composition, result publication, restart,
  redaction, and fail-closed regression: `250 passed`.
- Actual EOS protected PostgreSQL flow: `1 passed` against `nex_eos_test`.
  It created and verified Journal, SourcePool, AllocationBatch, and projections,
  then proved replay, restart, concurrency, authorization denial, and zero
  residue.
- Actual AE/WC PostgreSQL WorkIntent and approval publication flows: `2 passed`
  with protected tests explicitly enabled and no Slice-owned skip.
- Actual OA authorization PostgreSQL smoke: `PASS`; five audit events, two
  revoked sessions, restart readback, and residue `0`.
- Actual five-service OA/AE/WC/EOS/WA signed-trust and evidence-consumption
  smoke: `1 passed` with all five test database identities admitted.
- Actual WA durable intake and AE source projection: `2 passed`; replay reused
  the same job, changed source hash conflicted, and cleanup residue was zero.
- AE Slice Gate: `PASS`, `6516 passed`, `47` unrelated protected skips.
  - statement coverage: `96.43%` (threshold `95.00%`)
  - branch coverage: `94.63%` (threshold `94.00%`)
  - active product import graph: `95` modules
- Ruff and diff checks: pass.
- Repository Checkpoint Gate: `PASS`, `5/5` commands.
  - regression: `22579 passed`, `181` protected skips
  - statement coverage: `98.38%` (threshold `95.00%`)
  - branch coverage: `96.92%` (threshold `94.00%`)
  - contract validation: `272` schemas, `320` examples, `260` negative
    examples, and `10` OpenAPI documents
  - Golden journey transition audit: pass
  - demo/product dependency audit: pass
- Evidence:
  - `reports/quality/mybee-w70-cp-m1-e2e-fx-01b6-ae-slice-gate.json`
  - `reports/quality/mybee-w70-cp-m1-e2e-fx-01b6-checkpoint-gate.json`

The Starlette/httpx warning remains a non-blocking repository backlog item.

## Closure Decision

`CP-M1-E2E-FX-01B.6` is closed. The installed product path now reaches verified
allocation, EOS-owned Project P&L, redacted PA/WC result delivery, WA evidence
intake, and owner-visible IA publication without a runner-owned business
transition or scenario fixture.

The next Slice is `CP-M1-E2E-FX-01B.7`. It owns live Qwen3.5-9B planning,
authenticated public API and Playwright acceptance, non-identical business
variants, the exact M1 acceptance journey, and the Repository Full Gate.
