# P8-S44 Protected NSL ApprovalRequest Store

**Status:** PASS
**Date:** 2026-10-22

## Scope

P8-S44 adds the AE-owned protected persistence boundary for the exact canonical
NSL v0.2 `ApprovalRequest`. It deliberately does not create an approval wait,
publish a WC human task, or resume NSL execution. Those remain P8-S45 through
P8-S53 responsibilities.

The storage order is:

```text
NSL ApprovalRequest.to_data()
-> canonical JSON
-> shared nex_runtime semantic SHA-256
-> immutable AE private storage
-> metadata-only AE PostgreSQL row
```

## Ownership And Privacy

- AE owns the protected request and its metadata.
- The complete NSL request, including `message` and `protected_payload_ref`, is
  stored only through the AE private-storage port.
- PostgreSQL stores only the opaque reference, request hash, size, media type,
  classification, and bounded NSL/business identities.
- The opaque `ae://nsl-approval-requests/...` reference exposes no tenant,
  execution, business-operation, or approval-request identifier.
- WC approval rows continue to receive only `protected_request_ref`; no generic
  WC or RuntimeJob payload receives the protected body.

The private-storage implementation supports in-memory regression,
mode-`0600` filesystem storage, and the existing AE S3-compatible/RustFS port.
Object keys reuse the shared owner-scoped opaque-key builder and immutable
publish semantics.

## Persistence

Migration `2500_ae_nsl_approval_request` creates the short
`ae_nsl_approval_request` table. The primary identity is
`(tenant_id, approval_request_id)` and the opaque reference is independently
unique within the tenant.

Idempotency is fail-closed:

```text
same tenant + ApprovalRequestId + same canonical bytes -> existing record
same tenant + ApprovalRequestId + different bytes      -> conflict
missing/corrupt private body or metadata                -> integrity failure
private storage or PostgreSQL outage                    -> retryable unavailable
```

The body is stored before metadata publication. A retry after an interrupted
metadata write converges on the same immutable object and row identity.
The physical object identity also uses `(tenant_id, approval_request_id)`, so
reusing an ApprovalRequestId with a different NSL execution cannot publish an
orphan conflict object before PostgreSQL rejects it.

## Actual PostgreSQL Evidence

The migration was applied directly to `nex_ae_test` using the canonical
migration runner. Protected smoke then verified:

- migration ledger entry `2500_ae_nsl_approval_request`;
- the exact ten-column metadata-only table shape;
- no `request_json`, `message`, `protected_payload_ref`, or `payload` column;
- insert, select, exact private-body reload, and idempotent replay;
- changed-semantics conflict with one remaining row; and
- zero scoped rows after cleanup.

Result: `1 passed` against the actual PostgreSQL test database.

## Verification

- focused unit/SQLite regression: `26 passed`, `1 protected skip`
- focused S44 module coverage before the service gate: `98%`
- AE Slice Gate: PASS
  - Python: `4628 passed`, `18 protected skips`
  - statement coverage: `98.30%`
  - branch coverage: `96.15%`
  - S44 module statement coverage: `98.50%`
  - S44 module branch coverage: `95.35%`
  - contracts: `188` schemas, `250` examples, `217` negative examples,
    `9` OpenAPI documents
- remote embedding, reranking, and generation providers: not required

## Handoff

P8-S44 is closed. P8-S45 may generalize `ae_wait_registration` from the
P7-only `WORK_RESULT`/UUID external identity to a backward-compatible
`WORK_RESULT | NSL_APPROVAL` typed wait. It can bind the opaque reference
created here without moving or duplicating the protected body.
