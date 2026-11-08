# P8-S46 NSL Approval Wait Binding

**Status:** PASS
**Date:** 2026-10-22

## Scope

P8-S46 binds one AE `NSL_APPROVAL` wait to the exact immutable lineage needed
to resume a suspended NSL v0.2 execution:

```text
AgentExecutionId
ExecutableStepId
NSLExecutionId
BusinessOperationId
ApprovalRequestId
checkpoint_version
```

The existing `ae_wait_registration` source of record remains canonical. No
parallel approval-wait table was introduced, and historical `WORK_RESULT`
callers continue to store null NSL lineage.

## Persistence And Invariants

Migration `2503_ae_nsl_approval_wait_binding` adds four nullable lineage
columns to `ae_wait_registration`. Its constraints enforce:

- `WORK_RESULT` carries no NSL approval lineage;
- `NSL_APPROVAL` carries all four lineage values;
- `external_ref == approval_request_id`;
- `checkpoint_version` is a positive integer; and
- the combined request, NSL execution, and business operation lineage exists
  in the protected `ae_nsl_approval_request` store.

The repository applies the same fail-closed rules before persistence and
includes all lineage fields in immutable replay comparison. A deterministic
wait identity binds tenant, execution, step, request, and checkpoint version.

## Verification

- focused P7/P8 regression: `140 passed`, `3 protected skips`
- actual `nex_ae_test` migration: applied
- actual PostgreSQL protected smoke: `12 passed`
- database audit: migration ledger `1`, scoped wait rows `0`
- AE Slice Gate: PASS
  - Python: `4657 passed`, `20 protected skips`
  - statement coverage: `98.32%`
  - branch coverage: `96.21%`
  - `delegated_work.py` statement coverage: `98.11%`
  - `delegated_work.py` branch coverage: `100.00%`
  - contracts: `188` schemas, `250` examples, `217` negative examples,
    `9` OpenAPI documents
- remote providers: not required

## Handoff

P8-S47 can implement the NSL `ApprovalPort` publication adapter in the
required order: persist the protected request, ensure this exact durable AE
wait, then create or get the WC ApprovalWorkItem using the same
ApprovalRequestId.
