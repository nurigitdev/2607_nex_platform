# P8-S47 NSL ApprovalPort Publication Adapter

**Status:** PASS (changed-scope gate)
**Date:** 2026-10-22

## Scope

P8-S47 implements the NSL v0.2 `ApprovalPort` at the AE boundary. One
publication now follows this restart-safe order:

```text
resolve exact persisted checkpoint binding
-> persist exact protected ApprovalRequest in AE
-> ensure exact AE NSL_APPROVAL wait
-> WC create_or_get ApprovalWorkItem
```

The adapter binds the existing AgentExecution, ExecutableStep, NSLExecution,
BusinessOperation, ApprovalRequest, and positive checkpoint version. It does
not manufacture any new NSL identity. A WC failure leaves the AE request and
wait durable; retrying the same ApprovalRequestId converges on the same wait
and ApprovalWorkItem identifiers.

## Service Boundary

WC now exposes service-authenticated `POST /api/v1/approval-work-items` over
its existing `ApprovalWorkItemService.create_or_get` behavior. AE uses a thin
HTTP client and never imports WC implementation code at runtime.

The WC contract now admits a bounded opaque `protected_request_ref` up to 512
characters. This permits the canonical AE `ae://nsl-approval-requests/...`
reference while keeping the protected request body, NSL message, and private
payload reference out of WC.

UTC timestamps are normalized to `Z` before crossing into WC. This closes a
real PostgreSQL replay mismatch between NSL `+00:00` serialization and WC
read-model normalization.

## Verification

- focused approval regression: `209 passed`, `5 protected skips`
- new AE adapter focused coverage: statement `100%`, branch `100%`
- actual `nex_ae_test` + `nex_wc_test` protected smoke: `1 passed`
  - two identical publishes produce one protected request, one wait, and one
    WC ApprovalWorkItem
  - exact request, execution, operation, checkpoint, and opaque reference
    lineage was selected from both databases
  - all scoped rows were deleted after the test
- AE Slice Gate: PASS
  - Python: `4679 passed`, `21 protected skips`
  - statement coverage: `98.33%`
  - branch coverage: `96.22%`
  - adapter statement/branch coverage: `100% / 100%`
- WC service regression after ownership-pattern correction:
  - Python: `466 passed`, `15 protected skips`
  - `approval_api.py`: statement/branch `100% / 100%`
  - `approvals.py`: statement `98.59%`, branch `95.70%`
  - existing whole-WC baseline remains statement `92.08%`, branch `89.37%`;
    therefore the unscoped WC 95/94 command remains FAIL and was not hidden by
    lowering thresholds
- contracts: `188` schemas, `250` examples, `217` negative examples,
  `9` OpenAPI documents
- remote providers: not required

## Quality-Gate Ownership

The WC Slice Gate profile previously omitted the established cross-service
test namespaces `test_ae_wc_*` and `test_nex_ae_wc_*`. They are now included,
raising the measured whole-WC baseline without changing any threshold. The
remaining pre-existing WC-wide coverage gap is explicitly carried into the
mandatory post-S48 Checkpoint Gate rather than weakening the gate.

## Handoff

P8-S48 can persist AE-owned immutable Platform ApprovalEvidence. It may refer
to the exact wait and WC ApprovalWorkItem established here and must retain OA
decision authority plus NSL binding hashes in `evidence_integrity`.
