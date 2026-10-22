# P8-S44A ApprovalRequest PostgreSQL BYTEA Integration

**Status:** PASS
**Date:** 2026-10-22

## Decision

P8-S44A keeps the exact canonical NSL `ApprovalRequest` and its immutable
metadata inside the AE PostgreSQL system of record. The request is a bounded
JSON control envelope, not a generic binary artifact. Large or binary business
payloads remain separate and are referenced through `protected_payload_ref`.

```text
NSL ApprovalRequest.to_data()
-> canonical JSON bytes
-> shared nex_runtime SHA-256
-> ae_nsl_approval_request.approval_request_bytes BYTEA
-> metadata-safe repository projection
```

The existing opaque `ae://nsl-approval-requests/...` reference remains a
logical protected reference. It does not expose the tenant, approval identity,
or PostgreSQL implementation detail.

## Persistence

Migration `2501_ae_nsl_approval_request_body` adds
`approval_request_bytes BYTEA` to the existing short table. It enforces:

- `NOT NULL` canonical bytes;
- a one-byte to one-MiB database size check;
- fail-closed migration when a metadata-only row cannot be backfilled; and
- unchanged `(tenant_id, approval_request_id)` idempotency identity.

The repository inserts body and metadata in one transaction. The same identity
and same bytes return the existing record. Changed semantics fail closed. Every
read verifies hash, size, canonical JSON, exact ApprovalRequest fields, tenant,
NSL execution, business operation, classification, and request identity.

Public `persist()` and `get()` results contain only metadata. The private bytes
are returned only as the validated canonical request through `load_request()`.

## Removed ApprovalRequest-Specific Complexity

The P8-S44 filesystem and S3/RustFS ApprovalRequest body adapters and the
dedicated filesystem-root environment variable were removed. Existing AE
private object storage remains available for actual artifacts and large binary
payloads; it is no longer part of this small JSON envelope's consistency path.

## Verification

- focused SQLite/unit regression: `35 passed`, `1 protected skip`
- migration/readiness regression: `37 passed`, `1 protected skip`
- AE Slice Gate: PASS
  - Python: `4637 passed`, `18 protected skips`
  - statement coverage: `98.30%`
  - branch coverage: `96.16%`
  - S44A module statement coverage: `98.96%`
  - S44A module branch coverage: `97.83%`
  - contracts: `188` schemas, `250` examples, `217` negative examples,
    `9` OpenAPI documents
- actual `nex_ae_test` migration:
  `2501_ae_nsl_approval_request_body` applied
- actual PostgreSQL protected smoke: `1 passed`
- final database audit: migration ledger `1`, `bytea:NO`, scoped rows `0`
- remote embedding, reranking, and generation providers: not required

## Handoff

P8-S45 can consume the unchanged `protected_request_ref` and
`approval_request_hash` contract. It does not need filesystem or object-storage
configuration to bind an `NSL_APPROVAL` wait to the canonical request.
