# P8-S81: Approval Event ACK Loss

## Status

Completed on 2026-10-24. P8-S82 is next.

## Boundary

P8-S81 loses the first acknowledgement only after AE has durably accepted the
exact approval event:

```text
WC approval event delivery
-> AE inbox MATCHED
-> one deterministic RESUME_EXECUTION job persisted
-> delivery ACK discarded as TimeoutError
-> exact same event and approval binding retried
-> AE returns the existing inbox and resume job
-> one runtime claim consumes one NSL checkpoint
```

The retry boundary does not recreate the ApprovalRequest, Platform
ApprovalEvidence, wait, checkpoint, manifest, attachment, or EOS mutation.

## Source Audit and Implementation

The existing AE persistence already supplied the authoritative protections:

- `(tenant_id, event_id)` uniqueness in `ae_external_event_inbox`;
- semantic hash conflict detection for reused event identities;
- deterministic resume job identity and `(tenant_id, dedup_key)` uniqueness;
- exact wait, event, evidence, request, execution, and operation lineage checks;
- admitted NSL claim/checkpoint consumption.

No database table, migration, public API, or event schema changed.

`ApprovalEventAckLossFaultClient` adds a deterministic protected fault at the
transport boundary. It injects ACK loss only after the response proves
`MATCHED`, `RESUME_QUEUED`, and a concrete resume job ID. It records and
requires an immutable hash over:

```text
TenantId
ApprovalRequestId
ApprovalWorkItemRef
ApprovalEvidenceRef
EvidenceIntegrity
NSLExecutionId
BusinessOperationId
Decision
```

It also hashes the complete event. A retry with changed transport semantics or
approval binding fails before the delegate is invoked.

The P8-S53 actual resume harness now accepts an optional delivery-client
factory. Its default behavior is unchanged; P8-S81 alone activates ACK-loss
injection. This keeps the previous P8-S53 regression path available while
reusing its admitted NSL wheel, real checkpoint, runtime worker, and cleanup.

## Manifest and Object Boundary

Approval delivery contains bounded immutable references, not attachment bytes.
When a Voucher has attachments, its manifest is bound through the protected
ApprovalRequest and PayloadHash/ApprovalEvidence lineage. S81 preserves that
lineage hash exactly and never reads or writes RustFS.

Actual RustFS object and manifest immutability was already proven by P8-S75H
and P8-S76 through P8-S80. Re-running object storage for a reference-only event
retry would add no new mutation boundary. The complete attachment-bearing
reliability journey remains mandatory in P8-S86.

## Protected PostgreSQL Evidence

The protected S81 gate used the admitted NSL v0.2 wheel and actual:

```text
nex_ae_user @ nex_ae_test
nex_wc_user @ nex_wc_test
```

It ran APPROVE, REJECT, and expiry scenarios. Each scenario produced:

```text
delivery attempts                 = 2
durable downstream acceptances   = 2
confirmed acknowledgements       = 1
unique event IDs                  = 1
unique resume job IDs             = 1
ae_runtime_job RESUME rows        = 1
NSL claim consumed                = true
NSL checkpoint consumed           = true
runtime job final state           = DONE
EOS mutation count                = 0
test database residue             = 0
```

Every scenario retained one non-empty `sha256:` approval binding hash and the
exact ApprovalRequestId/PayloadHash evidence lineage.

Protected result:

```text
1 passed
0 skipped
```

Remote generation, embedding, and reranking providers were not required.
RustFS was not required because this Slice exercises reference delivery and
checkpoint consumption only.

## Regression and Quality Gate

Focused approval/resume and attachment-aware regression:

```text
717 passed
24 protected opt-in skipped
```

NeX-AE Slice Gate:

```text
pytest                       = 5,344 passed / 43 protected opt-in skipped
statement coverage           = 98.33% / required 95.00%
branch coverage              = 96.30% / required 94.00%
reliability fault scope      = 100.00% statement / 100.00% branch
contract validation          = 191 schemas / 253 positive / 221 negative / 9 OpenAPI
gate commands                = 4 / 4
gate exit                    = 0
```

The protected S81 scenario has separate zero-skip evidence above.

## Exit Decision

INV-12 is proven against actual AE/WC PostgreSQL and the admitted NSL runtime:
approval-event ACK loss may repeat delivery, but creates at most one semantic
resume and consumes the checkpoint once. P8-S82 may now inject a worker crash
after checkpoint persistence and prove restart recovery without duplicate
approval or manifest semantic work.
